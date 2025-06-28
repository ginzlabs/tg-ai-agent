

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;


CREATE EXTENSION IF NOT EXISTS "pg_cron" WITH SCHEMA "pg_catalog";






CREATE EXTENSION IF NOT EXISTS "pg_net" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "pgsodium";






COMMENT ON SCHEMA "public" IS 'standard public schema';



CREATE EXTENSION IF NOT EXISTS "pg_graphql" WITH SCHEMA "graphql";






CREATE EXTENSION IF NOT EXISTS "pg_stat_statements" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "pgcrypto" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "pgjwt" WITH SCHEMA "extensions";






CREATE EXTENSION IF NOT EXISTS "supabase_vault" WITH SCHEMA "vault";






CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA "extensions";






CREATE OR REPLACE FUNCTION "public"."call_process_message"("p_prompt_text" "text", "p_chat_id" bigint, "p_db_thread_id" "text", "p_message_id" "text" DEFAULT NULL::"text", "p_file_url" "text" DEFAULT NULL::"text") RETURNS "jsonb"
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
DECLARE
    _url text;
    _token text;
    _response jsonb;
BEGIN
    -- Get server config
    SELECT bot_server_url, our_secret_token
    INTO _url, _token
    FROM public.server_settings
    ORDER BY id DESC
    LIMIT 1;

    IF _url IS NULL THEN
        RAISE EXCEPTION 'bot_server_url not set in server_settings';
    END IF;

    _url := _url || '/process_message';

    -- Make the HTTP request using the net extension
    SELECT net.http_post(
        url := _url,
        body := jsonb_build_object(
            'chat_id', p_chat_id,
            'text', p_prompt_text,
            'message_id', p_message_id,
            'file_url', p_file_url,
            'db_thread_id', p_db_thread_id
        ),
        headers := jsonb_build_object(
            'Content-Type', 'application/json',
            'X-Secret-Token', _token
        ),
        timeout_milliseconds := 5000
    )
    INTO _response;

    RETURN _response;
END;
$$;


ALTER FUNCTION "public"."call_process_message"("p_prompt_text" "text", "p_chat_id" bigint, "p_db_thread_id" "text", "p_message_id" "text", "p_file_url" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."check_tool_access"("chat_id_input" bigint, "tool_name_input" "text") RETURNS boolean
    LANGUAGE "plpgsql"
    AS $$
declare
  user_tier int;
  tool_required_tier int;
begin
  -- Fetch user tier
  select tier into user_tier
  from public.chats
  where chat_id = chat_id_input;

  if user_tier is null then
    return false; -- Chat/user not found
  end if;

  -- Fetch tool tier
  select tool_tier into tool_required_tier
  from public.tools
  where tool_name = tool_name_input;

  if tool_required_tier is null then
    return false; -- Tool not found or improperly defined
  end if;

  -- Check access
  return user_tier >= tool_required_tier;
end;
$$;


ALTER FUNCTION "public"."check_tool_access"("chat_id_input" bigint, "tool_name_input" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."clear_user_dialog"("p_chat_id" bigint, "p_thread_id" "text") RETURNS "jsonb"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    _user_exists BOOLEAN;
    _deleted_blobs INTEGER := 0;
    _deleted_writes INTEGER := 0;
    _deleted_checkpoints INTEGER := 0;
BEGIN
    -- Check if the user exists
    SELECT EXISTS (
        SELECT 1 FROM chats WHERE chat_id = p_chat_id
    ) INTO _user_exists;

    IF NOT _user_exists THEN
        RETURN jsonb_build_object(
            'success', false,
            'message', 'User not found'
        );
    END IF;

    -- Start deletion in a transactional block
    DELETE FROM checkpoint_blobs
    WHERE thread_id = p_thread_id;
    GET DIAGNOSTICS _deleted_blobs = ROW_COUNT;

    DELETE FROM checkpoint_writes
    WHERE thread_id = p_thread_id;
    GET DIAGNOSTICS _deleted_writes = ROW_COUNT;

    DELETE FROM checkpoints
    WHERE thread_id = p_thread_id;
    GET DIAGNOSTICS _deleted_checkpoints = ROW_COUNT;

    RETURN jsonb_build_object(
        'success', true,
        'thread_id', p_thread_id,
        'deleted_blobs', _deleted_blobs,
        'deleted_writes', _deleted_writes,
        'deleted_checkpoints', _deleted_checkpoints
    );
END;
$$;


ALTER FUNCTION "public"."clear_user_dialog"("p_chat_id" bigint, "p_thread_id" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."clear_user_memory"("p_chat_id" bigint, "p_thread_id" "text") RETURNS "jsonb"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    _prefix TEXT := 'memories.' || p_chat_id;
    _deleted_count INTEGER;
BEGIN
    DELETE FROM store
    WHERE prefix = _prefix;

    GET DIAGNOSTICS _deleted_count = ROW_COUNT;

    RETURN jsonb_build_object(
        'success', true,
        'deleted_count', _deleted_count,
        'prefix', _prefix
    );
END;
$$;


ALTER FUNCTION "public"."clear_user_memory"("p_chat_id" bigint, "p_thread_id" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."create_cron_prompt_job"("p_chat_id" bigint, "p_prompt_text" "text", "p_jobname" "text", "p_schedule" "text", "p_db_thread_id" "text", "p_message_id" "text" DEFAULT NULL::"text", "p_file_url" "text" DEFAULT NULL::"text") RETURNS TABLE("result" "jsonb")
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $_$
DECLARE
    _jobid bigint;
    _command text;
    _prompt_id text;
    _tier integer;
    _crons_limit integer;
    _existing_crons integer;
BEGIN
    -- Step 1: Get user's tier
    SELECT tier INTO _tier
    FROM public.chats
    WHERE chat_id = p_chat_id;

    IF _tier IS NULL THEN
        RETURN QUERY SELECT jsonb_build_object(
            'success', false,
            'message', format('User not found for chat_id %s', p_chat_id)
        );
        RETURN;
    END IF;

    -- Step 2: Get tier's cron limit
    SELECT crons_limit INTO _crons_limit
    FROM public.tier_rate_limits
    WHERE tier = _tier;

    IF _crons_limit IS NULL THEN
        _crons_limit := 0;
    END IF;

    -- Step 3: Count existing cron jobs for the user
    SELECT COUNT(*) INTO _existing_crons
    FROM public.cron_prompts
    WHERE chat_id = p_chat_id;

    -- Step 4: Block if over limit
    IF _existing_crons >= _crons_limit THEN
        RETURN QUERY SELECT jsonb_build_object(
            'success', false,
            'message', format('Cron limit reached. Tier %s allows up to %s cron jobs.', _tier, _crons_limit)
        );
        RETURN;
    END IF;

    -- Step 5: Build command
    _command := format(
        $$SELECT public.call_process_message(
            %L, %s, %L, %L, %L);$$,
        p_prompt_text,
        p_chat_id,
        p_db_thread_id,
        p_message_id,
        p_file_url
    );

    -- Step 6: Schedule the cron job
    SELECT cron.schedule(
        p_jobname,
        p_schedule,
        _command
    ) INTO _jobid;

    -- Step 7: Retry insert up to 3 times on ID collision
    FOR i IN 1..3 LOOP
        BEGIN
            _prompt_id := nanoid(5, '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ');
            INSERT INTO public.cron_prompts (
                id, chat_id, jobname, prompt_text, schedule, jobid
            )
            VALUES (
                _prompt_id, p_chat_id, p_jobname, p_prompt_text, p_schedule, _jobid
            );
            EXIT;
        EXCEPTION WHEN unique_violation THEN
            IF i = 3 THEN
                RAISE EXCEPTION 'Failed to insert cron_prompt after 3 attempts.';
            END IF;
        END;
    END LOOP;

    -- Step 8: Return the result as a named field
    RETURN QUERY SELECT jsonb_build_object(
        'success', true,
        'prompt_id', _prompt_id,
        'jobid', _jobid,
        'jobname', p_jobname,
        'message', 'Cron job and prompt created successfully.'
    );
END;
$_$;


ALTER FUNCTION "public"."create_cron_prompt_job"("p_chat_id" bigint, "p_prompt_text" "text", "p_jobname" "text", "p_schedule" "text", "p_db_thread_id" "text", "p_message_id" "text", "p_file_url" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."delete_cron_prompt"("p_id" "text", "p_chat_id" bigint) RETURNS TABLE("result" "jsonb")
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
DECLARE
    _jobid bigint;
    _job_exists boolean;
BEGIN
    -- Fetch jobid from our tracking table
    SELECT jobid INTO _jobid
    FROM public.cron_prompts
    WHERE id = p_id AND chat_id = p_chat_id;

    IF NOT FOUND THEN
        RETURN QUERY SELECT jsonb_build_object(
            'success', false,
            'message', 'Cron prompt not found.'
        );
        RETURN;
    END IF;

    -- Check if the job actually exists in cron.job
    SELECT EXISTS (
        SELECT 1 FROM cron.job WHERE jobid = _jobid
    ) INTO _job_exists;

    -- Unschedule only if job still exists
    IF _job_exists THEN
        PERFORM cron.unschedule(_jobid);
    END IF;

    -- Always remove the prompt record
    DELETE FROM public.cron_prompts
    WHERE id = p_id AND chat_id = p_chat_id;

    -- Return final result
    RETURN QUERY SELECT jsonb_build_object(
        'success', true,
        'job_unscheduled', _job_exists,
        'message', 'Cron prompt deleted. Job was ' ||
                   CASE WHEN _job_exists THEN 'unscheduled.' ELSE 'already missing from cron.job.' END
    );
END;
$$;


ALTER FUNCTION "public"."delete_cron_prompt"("p_id" "text", "p_chat_id" bigint) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."delete_user"("p_chat_id" bigint DEFAULT NULL::bigint, "p_user_name" "text" DEFAULT NULL::"text") RETURNS TABLE("result" "jsonb")
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$
DECLARE
    _chat_id bigint;
    _path_prefix text;
BEGIN
    -- Ensure at least one identifier is provided
    IF p_chat_id IS NULL AND p_user_name IS NULL THEN
        RETURN QUERY SELECT jsonb_build_object(
            'success', false,
            'message', 'You must provide either chat_id or user_name.'
        );
        RETURN;
    END IF;

    -- If chat_id is provided, use it
    IF p_chat_id IS NOT NULL THEN
        _chat_id := p_chat_id;
    ELSE
        -- Try to find chat_id using user_name
        SELECT chat_id INTO _chat_id
        FROM public.chats
        WHERE user_name = p_user_name;

        -- If not found, delete from chats using user_name and exit
        IF _chat_id IS NULL THEN
            DELETE FROM public.chats
            WHERE user_name = p_user_name;

            RETURN QUERY SELECT jsonb_build_object(
                'success', true,
                'message', 'User deleted from chats using user_name. No chat_id found, so no files were deleted.',
                'user_name', p_user_name
            );
            RETURN;
        END IF;
    END IF;

    -- Delete related stt_files
    DELETE FROM public.stt_files
    WHERE chat_id = _chat_id;

    -- Delete from chats
    DELETE FROM public.chats
    WHERE chat_id = _chat_id;

    -- Prepare storage path prefix
    _path_prefix := _chat_id::text || '/';

    -- Delete objects in all relevant buckets
    DELETE FROM storage.objects
    WHERE bucket_id IN ('stt_files', 'awex_reports', 'reports')
      AND name LIKE _path_prefix || '%';

    -- Return success
    RETURN QUERY SELECT jsonb_build_object(
        'success', true,
        'message', 'User and all related files deleted successfully.',
        'chat_id', _chat_id
    );
END;
$$;


ALTER FUNCTION "public"."delete_user"("p_chat_id" bigint, "p_user_name" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_allowed_llms"("p_chat_id" bigint) RETURNS TABLE("result" "jsonb")
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    _allowed_llms text[];
    _user_llm text;
BEGIN
    -- Get allowed LLMs from server settings
    SELECT allowed_llms
    INTO _allowed_llms
    FROM public.server_settings
    ORDER BY id DESC
    LIMIT 1;

    -- Get the user's current LLM
    SELECT llm_choice
    INTO _user_llm
    FROM public.chats
    WHERE chat_id = p_chat_id;

    -- Return combined result
    RETURN QUERY
    SELECT jsonb_build_object(
        'success', true,
        'allowed_llms', COALESCE(_allowed_llms, ARRAY[]::text[]),
        'llm_choice', _user_llm
    );
END;
$$;


ALTER FUNCTION "public"."get_allowed_llms"("p_chat_id" bigint) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_available_tools"("p_chat_id" bigint) RETURNS "jsonb"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    _user_tier INTEGER;
BEGIN
    -- Get the user's tier
    SELECT tier INTO _user_tier
    FROM chats
    WHERE chat_id = p_chat_id;

    -- If user doesn't exist, return empty list
    IF _user_tier IS NULL THEN
        RETURN jsonb_build_array();
    END IF;

    -- Return tools as JSON array where tool_tier <= user_tier
    RETURN (
        SELECT jsonb_agg(
            jsonb_build_object(
                'tool_name', tool_name,
                'tool_description', tool_description,
                'tool_tier', tool_tier
            )
        )
        FROM tools
        WHERE tool_tier IS NULL OR tool_tier <= _user_tier
    );
END;
$$;


ALTER FUNCTION "public"."get_available_tools"("p_chat_id" bigint) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_user_limits"("p_chat_id" bigint) RETURNS "jsonb"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    _daily_usage INTEGER;
    _monthly_usage INTEGER;
    _tier INTEGER;
    _daily_limit INTEGER;
    _monthly_limit INTEGER;
    _pause_seconds INTEGER;
    _crons_limit INTEGER;
    _cron_usage INTEGER;
BEGIN
    -- Get user's tier and usage
    SELECT tier, daily_usage, monthly_usage
    INTO _tier, _daily_usage, _monthly_usage
    FROM chats
    WHERE chat_id = p_chat_id;

    -- If user not found
    IF _tier IS NULL THEN
        RETURN jsonb_build_object(
            'error', 'User not found',
            'daily_usage', 0,
            'monthly_usage', 0,
            'daily_limit', 0,
            'monthly_limit', 0,
            'pause_seconds', 0,
            'cron_usage', 0,
            'crons_limit', 0
        );
    END IF;

    -- Get tier rate limits
    SELECT daily_limit, monthly_limit, pause_seconds, crons_limit
    INTO _daily_limit, _monthly_limit, _pause_seconds, _crons_limit
    FROM tier_rate_limits
    WHERE tier = _tier
    LIMIT 1;

    -- Count current cron jobs
    SELECT COUNT(*) INTO _cron_usage
    FROM cron_prompts
    WHERE chat_id = p_chat_id;

    RETURN jsonb_build_object(
        'daily_usage', _daily_usage,
        'monthly_usage', _monthly_usage,
        'daily_limit', COALESCE(_daily_limit, 0),
        'monthly_limit', COALESCE(_monthly_limit, 0),
        'pause_seconds', COALESCE(_pause_seconds, 0),
        'cron_usage', _cron_usage,
        'crons_limit', COALESCE(_crons_limit, 0)
    );
END;
$$;


ALTER FUNCTION "public"."get_user_limits"("p_chat_id" bigint) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."get_user_profile_and_tools"("p_chat_id" bigint) RETURNS TABLE("result" "jsonb")
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    _tier int;
    _expire_at timestamptz;
BEGIN
    -- Fetch user's tier and expiration
    SELECT tier, expire_at INTO _tier, _expire_at
    FROM public.chats
    WHERE chat_id = p_chat_id;

    IF _tier IS NULL THEN
        RETURN QUERY SELECT jsonb_build_object(
            'success', false,
            'message', 'User not found.'
        );
        RETURN;
    END IF;

    -- Return tools allowed at this tier
    RETURN QUERY
    SELECT jsonb_build_object(
        'success', true,
        'tier', _tier,
        'expire_at', _expire_at,
        'tools', (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'tool_title', tool_title,
                    'tool_description', tool_description
                )
            )
            FROM public.tools
            WHERE tool_tier IS NULL OR tool_tier <= _tier
        )
    );
END;
$$;


ALTER FUNCTION "public"."get_user_profile_and_tools"("p_chat_id" bigint) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."list_cron_prompts_by_chat"("p_chat_id" bigint) RETURNS "jsonb"
    LANGUAGE "sql"
    AS $$
SELECT jsonb_agg(
    jsonb_build_object(
        'id', id,
        'prompt_text', prompt_text,
        'schedule', schedule
    )
)
FROM public.cron_prompts
WHERE chat_id = p_chat_id;
$$;


ALTER FUNCTION "public"."list_cron_prompts_by_chat"("p_chat_id" bigint) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."nanoid"("size" integer DEFAULT 21, "alphabet" "text" DEFAULT '_-0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'::"text") RETURNS "text"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    idBuilder     text := '';
    i             int  := 0;
    bytes         bytea;
    alphabetIndex int;
    mask          int;
    step          int;
BEGIN
    mask := (2 << cast(floor(log(length(alphabet) - 1) / log(2)) as int)) - 1;
    step := cast(ceil(1.6 * mask * size / length(alphabet)) AS int);

    while true
    loop
        bytes := gen_random_bytes(size);
        while i < size
        loop
            alphabetIndex := (get_byte(bytes, i) & mask) + 1;
            if alphabetIndex <= length(alphabet) then
                idBuilder := idBuilder || substr(alphabet, alphabetIndex, 1);
                if length(idBuilder) = size then
                    return idBuilder;
                end if;
            end if;
            i = i + 1;
        end loop;
        i := 0;
    end loop;
END
$$;


ALTER FUNCTION "public"."nanoid"("size" integer, "alphabet" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."reset_daily_usage"() RETURNS "void"
    LANGUAGE "sql"
    AS $$
    UPDATE chats SET daily_usage = 0;
$$;


ALTER FUNCTION "public"."reset_daily_usage"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."reset_monthly_usage"() RETURNS "void"
    LANGUAGE "sql"
    AS $$
    UPDATE chats SET monthly_usage = 0;
$$;


ALTER FUNCTION "public"."reset_monthly_usage"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."set_service_maintenance"("p_enabled" boolean) RETURNS "jsonb"
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    _affected_rows INTEGER;
BEGIN
    UPDATE chats
    SET service_maintenance = p_enabled
    WHERE role != 'admin';

    GET DIAGNOSTICS _affected_rows = ROW_COUNT;

    RETURN json_build_object(
        'success', true,
        'affected_users', _affected_rows,
        'service_maintenance', p_enabled
    );
END;
$$;


ALTER FUNCTION "public"."set_service_maintenance"("p_enabled" boolean) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."set_user_llm"("p_chat_id" bigint, "p_llm_choice" "text") RETURNS TABLE("result" "jsonb")
    LANGUAGE "plpgsql"
    AS $$
DECLARE
    _allowed_llms text[];
    _updated integer;
BEGIN
    -- Fetch the allowed LLMs from the latest server_settings row
    SELECT allowed_llms INTO _allowed_llms
    FROM public.server_settings
    ORDER BY id DESC
    LIMIT 1;

    -- Validate if the requested LLM is allowed
    IF NOT (p_llm_choice = ANY(_allowed_llms)) THEN
        RETURN QUERY SELECT jsonb_build_object(
            'success', false,
            'message', 'Requested LLM is not allowed.',
            'llm_choice', p_llm_choice,
            'allowed_llms', COALESCE(_allowed_llms, ARRAY[]::text[])
        );
        RETURN;
    END IF;

    -- Attempt to update the user's LLM
    UPDATE public.chats
    SET llm_choice = p_llm_choice
    WHERE chat_id = p_chat_id
    RETURNING 1 INTO _updated;

    IF _updated IS NULL THEN
        RETURN QUERY SELECT jsonb_build_object(
            'success', false,
            'message', 'User not found or update failed.',
            'llm_choice', p_llm_choice
        );
        RETURN;
    END IF;

    RETURN QUERY SELECT jsonb_build_object(
        'success', true,
        'llm_choice', p_llm_choice,
        'message', 'LLM choice updated successfully.'
    );
END;
$$;


ALTER FUNCTION "public"."set_user_llm"("p_chat_id" bigint, "p_llm_choice" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_cron_prompt"("p_id" "text", "p_chat_id" bigint, "p_prompt_text" "text", "p_schedule" "text", "p_db_thread_id" "text") RETURNS TABLE("result" "jsonb")
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $_$
DECLARE
    _existing RECORD;
    _token TEXT;
    _new_command TEXT;
    _new_jobid BIGINT;
BEGIN
    -- Fetch existing prompt
    SELECT * INTO _existing
    FROM public.cron_prompts
    WHERE id = p_id AND chat_id = p_chat_id;

    IF NOT FOUND THEN
        RETURN QUERY SELECT jsonb_build_object(
            'success', false,
            'message', 'Prompt not found.'
        );
        RETURN;
    END IF;

    -- Get latest secret token
    SELECT our_secret_token INTO _token
    FROM public.server_settings
    ORDER BY id DESC LIMIT 1;

    -- Build updated command with required thread_id
    _new_command := format(
        $$SELECT public.call_process_message(
            %L, %s, %L, NULL, NULL);$$,
        COALESCE(p_prompt_text, _existing.prompt_text),
        _existing.chat_id,
        p_db_thread_id
    );

    -- Unschedule old job
    PERFORM cron.unschedule(_existing.jobid);

    -- Schedule new job
    SELECT cron.schedule(
        _existing.jobname,
        COALESCE(p_schedule, _existing.schedule),
        _new_command
    ) INTO _new_jobid;

    -- Update record
    UPDATE public.cron_prompts
    SET
        prompt_text = COALESCE(p_prompt_text, prompt_text),
        schedule = COALESCE(p_schedule, schedule),
        jobid = _new_jobid
    WHERE id = p_id AND chat_id = p_chat_id;

    -- Return success
    RETURN QUERY SELECT jsonb_build_object(
        'success', true,
        'message', 'Cron prompt and job updated successfully.',
        'jobid', _new_jobid,
        'jobname', _existing.jobname
    );
END;
$_$;


ALTER FUNCTION "public"."update_cron_prompt"("p_id" "text", "p_chat_id" bigint, "p_prompt_text" "text", "p_schedule" "text", "p_db_thread_id" "text") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_cron_prompts_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_cron_prompts_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_stt_files_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$
BEGIN
    NEW.updated_at = now();
    
    -- If status is changing to 'completed' or 'error' and processed_at is not set yet
    IF (NEW.status = 'completed' OR NEW.status = 'error') AND NEW.processed_at IS NULL THEN
        NEW.processed_at = now();
    END IF;
    
    -- Calculate processing_time when processed_at is set
    IF NEW.processed_at IS NOT NULL AND NEW.processing_time IS NULL THEN
        NEW.processing_time = EXTRACT(EPOCH FROM (NEW.processed_at - NEW.created_at))::INTEGER;
    END IF;
    
    RETURN NEW;
END;
$$;


ALTER FUNCTION "public"."update_stt_files_updated_at"() OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."user_auth_checks"("p_chat_id" bigint, "p_user_name" "text") RETURNS "jsonb"
    LANGUAGE "plpgsql"
    AS $$DECLARE
    _chat chats%ROWTYPE;
    _now TIMESTAMPTZ := NOW();
    _pause_seconds INTEGER;
    _daily_limit INTEGER;
    _monthly_limit INTEGER;
    retry_seconds INTEGER;
    _db_thread_id UUID;
BEGIN
    -- Attempt to fetch the user by matching either the chat_id or user_name.
    SELECT * INTO _chat 
    FROM chats 
    WHERE (chat_id = p_chat_id OR user_name = p_user_name)
    LIMIT 1;

    IF _chat IS NULL THEN
        RETURN json_build_object(
            'allowed', false,
            'user_active', false,
            'message', 'User does not exist'
        );
    END IF;

    -- Get the most recent thread ID for the user (if exists)
    SELECT id INTO _db_thread_id
    FROM threads
    WHERE user_id = _chat.id
    ORDER BY created_at DESC
    LIMIT 1;

    -- Γëí╞Æ┬ó├íΓê⌐Γòò├à Service maintenance check
    IF _chat.service_maintenance THEN
        RETURN json_build_object(
            'allowed', false,
            'user_active', false,
            'message', 'Service is temporarily under maintenance. Please try again later.',
            'role', _chat.role,
            'llm_choice', _chat.llm_choice
        );
    END IF;

    -- Γëí╞Æ├£┬╜ Suspended check
    IF _chat.suspended THEN
        RETURN json_build_object(
            'allowed', false,
            'user_active', false,
            'message', 'Your subscription is suspended',
            'role', _chat.role,
            'llm_choice', _chat.llm_choice
        );
    END IF;

    -- Γëí╞Æ├£┬╜ Expired check
    IF _chat.expire_at IS NOT NULL AND _now > _chat.expire_at THEN
        RETURN json_build_object(
            'allowed', false,
            'user_active', false,
            'message', 'Your subscription has expired',
            'role', _chat.role,
            'llm_choice', _chat.llm_choice
        );
    END IF;

    -- New user: join and activate
    IF _chat.status = 'created' THEN
        UPDATE chats 
        SET chat_id = COALESCE(_chat.chat_id, p_chat_id),
            user_name = COALESCE(_chat.user_name, p_user_name),
            joined_at = _now,
            status = 'joined',
            active = true,
            messages_count = messages_count + 1
        WHERE id = _chat.id;

        RETURN json_build_object(
            'allowed', true,
            'first_interaction', true,
            'user_active', true,
            'joined_at', _now,
            'db_chat_id', _chat.id,
            'db_thread_id', _db_thread_id,
            'role', _chat.role,
            'llm_choice', _chat.llm_choice
        );
    END IF;

    -- Inactive user
    IF NOT _chat.active THEN
        RETURN json_build_object(
            'allowed', false,
            'user_active', false,
            'message', 'User not active',
            'role', _chat.role,
            'llm_choice', _chat.llm_choice
        );
    END IF;

    -- Get rate limits
    SELECT pause_seconds, daily_limit, monthly_limit 
    INTO _pause_seconds, _daily_limit, _monthly_limit
    FROM tier_rate_limits 
    WHERE tier = _chat.tier
    LIMIT 1;

    -- Daily limit
    IF _chat.daily_usage >= _daily_limit THEN
        RETURN json_build_object(
            'allowed', false,
            'limit_exceeded', 'daily',
            'daily_usage', _chat.daily_usage,
            'daily_limit', _daily_limit,
            'user_active', true,
            'joined_at', _chat.joined_at,
            'db_chat_id', _chat.id,
            'db_thread_id', _db_thread_id,
            'role', _chat.role,
            'llm_choice', _chat.llm_choice,
            'message', 'Daily limit exceeded. Your daily limit is ' || _daily_limit || ' messages.'
        );
    END IF;

    -- Monthly limit
    IF _chat.monthly_usage >= _monthly_limit THEN
        RETURN json_build_object(
            'allowed', false,
            'limit_exceeded', 'monthly',
            'monthly_usage', _chat.monthly_usage,
            'monthly_limit', _monthly_limit,
            'user_active', true,
            'joined_at', _chat.joined_at,
            'db_chat_id', _chat.id,
            'db_thread_id', _db_thread_id,
            'role', _chat.role,
            'llm_choice', _chat.llm_choice,
            'message', 'Monthly limit exceeded. Your monthly limit is ' || _monthly_limit || ' messages.'
        );
    END IF;

    -- Pause interval
    IF _chat.last_message_time IS NOT NULL AND
       _now < _chat.last_message_time + (_pause_seconds || ' seconds')::interval THEN
        retry_seconds := CEIL(EXTRACT(EPOCH FROM (_chat.last_message_time + (_pause_seconds || ' seconds')::interval - _now)));
        RETURN json_build_object(
            'allowed', false,
            'limit_exceeded', 'pause',
            'retry_after', retry_seconds,
            'user_active', true,
            'joined_at', _chat.joined_at,
            'db_chat_id', _chat.id,
            'db_thread_id', _db_thread_id,
            'role', _chat.role,
            'llm_choice', _chat.llm_choice,
            'message', 'Pause interval not elapsed. Please wait ' || retry_seconds || ' seconds.'
        );
    END IF;

    -- All checks passed: update usage counters
    UPDATE chats 
    SET last_message_time = _now,
        daily_usage = daily_usage + 1,
        monthly_usage = monthly_usage + 1,
        messages_count = messages_count + 1
    WHERE id = _chat.id;

    RETURN json_build_object(
        'allowed', true,
        'user_active', true,
        'joined_at', _chat.joined_at,
        'db_chat_id', _chat.id,
        'db_thread_id', _db_thread_id,
        'role', _chat.role,
        'llm_choice', _chat.llm_choice
    );
END;$$;


ALTER FUNCTION "public"."user_auth_checks"("p_chat_id" bigint, "p_user_name" "text") OWNER TO "postgres";

SET default_tablespace = '';

SET default_table_access_method = "heap";


CREATE TABLE IF NOT EXISTS "public"."chats" (
    "id" integer NOT NULL,
    "chat_id" bigint,
    "user_name" "text",
    "role" "text" NOT NULL,
    "status" "text" DEFAULT 'created'::"text" NOT NULL,
    "tier" integer DEFAULT 1 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "joined_at" timestamp with time zone,
    "banned_at" timestamp with time zone,
    "messages_count" integer DEFAULT 0 NOT NULL,
    "active" boolean DEFAULT false NOT NULL,
    "daily_usage" integer DEFAULT 0 NOT NULL,
    "monthly_usage" integer DEFAULT 0 NOT NULL,
    "last_message_time" timestamp with time zone,
    "expire_at" timestamp with time zone,
    "suspended" boolean,
    "service_maintenance" boolean,
    "llm_choice" "text" DEFAULT 'openai/gpt-4o-mini'::"text" NOT NULL
);


ALTER TABLE "public"."chats" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."chats_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE "public"."chats_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."chats_id_seq" OWNED BY "public"."chats"."id";



CREATE TABLE IF NOT EXISTS "public"."checkpoint_blobs" (
    "thread_id" "text" NOT NULL,
    "checkpoint_ns" "text" DEFAULT ''::"text" NOT NULL,
    "channel" "text" NOT NULL,
    "version" "text" NOT NULL,
    "type" "text" NOT NULL,
    "blob" "bytea"
);


ALTER TABLE "public"."checkpoint_blobs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."checkpoint_migrations" (
    "v" integer NOT NULL
);


ALTER TABLE "public"."checkpoint_migrations" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."checkpoint_writes" (
    "thread_id" "text" NOT NULL,
    "checkpoint_ns" "text" DEFAULT ''::"text" NOT NULL,
    "checkpoint_id" "text" NOT NULL,
    "task_id" "text" NOT NULL,
    "idx" integer NOT NULL,
    "channel" "text" NOT NULL,
    "type" "text",
    "blob" "bytea" NOT NULL,
    "task_path" "text" DEFAULT ''::"text" NOT NULL
);


ALTER TABLE "public"."checkpoint_writes" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."checkpoints" (
    "thread_id" "text" NOT NULL,
    "checkpoint_ns" "text" DEFAULT ''::"text" NOT NULL,
    "checkpoint_id" "text" NOT NULL,
    "parent_checkpoint_id" "text",
    "type" "text",
    "checkpoint" "jsonb" NOT NULL,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL
);


ALTER TABLE "public"."checkpoints" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."cron_prompts" (
    "id" "text" DEFAULT "public"."nanoid"() NOT NULL,
    "chat_id" bigint NOT NULL,
    "jobname" "text" NOT NULL,
    "prompt_text" "text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "updated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "schedule" "text" NOT NULL,
    "jobid" bigint NOT NULL
);


ALTER TABLE "public"."cron_prompts" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."endpoint_rate_limits" (
    "id" integer NOT NULL,
    "endpoint" "text" NOT NULL,
    "call_limit" integer NOT NULL,
    "interval_seconds" integer NOT NULL
);


ALTER TABLE "public"."endpoint_rate_limits" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."endpoint_rate_limits_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE "public"."endpoint_rate_limits_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."endpoint_rate_limits_id_seq" OWNED BY "public"."endpoint_rate_limits"."id";



CREATE TABLE IF NOT EXISTS "public"."file_messages" (
    "id" integer NOT NULL,
    "chat_id" bigint NOT NULL,
    "message_id" bigint NOT NULL,
    "text" "text",
    "date" bigint,
    "username" "text",
    "file_id" "text",
    "file_name" "text",
    "mime_type" "text",
    "file_size" bigint,
    "file_url" "text",
    "caption" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "file_type" "text",
    "db_thread_id" "uuid",
    "llm_choice" "text",
    "role" "text"
);


ALTER TABLE "public"."file_messages" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."file_messages_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE "public"."file_messages_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."file_messages_id_seq" OWNED BY "public"."file_messages"."id";



CREATE TABLE IF NOT EXISTS "public"."server_settings" (
    "id" integer NOT NULL,
    "our_secret_token" "text" NOT NULL,
    "bot_server_url" "text" NOT NULL,
    "description" "text",
    "allowed_llms" "text"[] DEFAULT ARRAY[]::"text"[]
);


ALTER TABLE "public"."server_settings" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."server_settings_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE "public"."server_settings_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."server_settings_id_seq" OWNED BY "public"."server_settings"."id";



CREATE TABLE IF NOT EXISTS "public"."store" (
    "prefix" "text" NOT NULL,
    "key" "text" NOT NULL,
    "value" "jsonb" NOT NULL,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "expires_at" timestamp with time zone,
    "ttl_minutes" integer
);


ALTER TABLE "public"."store" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."store_migrations" (
    "v" integer NOT NULL
);


ALTER TABLE "public"."store_migrations" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."stt_files" (
    "id" "uuid" DEFAULT "extensions"."uuid_generate_v4"() NOT NULL,
    "chat_id" bigint NOT NULL,
    "message_id" bigint NOT NULL,
    "audio_url" "text" NOT NULL,
    "transcript" "text",
    "status" "text" DEFAULT 'requested'::"text" NOT NULL,
    "stt_config" "jsonb",
    "error" "text",
    "model_used" "text",
    "detected_language" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    "transcript_id" "text",
    "processed_at" timestamp with time zone,
    "processing_time" integer,
    "transcript_docx_path" "text",
    "temp_msg_id" bigint,
    "delivered_to_user" boolean,
    "db_thread_id" "uuid",
    CONSTRAINT "stt_files_status_check" CHECK (("status" = ANY (ARRAY['requested'::"text", 'processing'::"text", 'completed'::"text", 'error'::"text"])))
);


ALTER TABLE "public"."stt_files" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."threads" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" integer,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL
);


ALTER TABLE "public"."threads" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."tier_rate_limits" (
    "id" integer NOT NULL,
    "tier" integer NOT NULL,
    "pause_seconds" integer NOT NULL,
    "daily_limit" integer NOT NULL,
    "monthly_limit" integer NOT NULL,
    "crons_limit" smallint
);


ALTER TABLE "public"."tier_rate_limits" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."tier_rate_limits_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE "public"."tier_rate_limits_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."tier_rate_limits_id_seq" OWNED BY "public"."tier_rate_limits"."id";



CREATE TABLE IF NOT EXISTS "public"."tools" (
    "tool_id" integer NOT NULL,
    "tool_name" "text" NOT NULL,
    "tool_description" "text",
    "tool_tier" bigint,
    "tool_config" "jsonb",
    "tool_title" "text"
);


ALTER TABLE "public"."tools" OWNER TO "postgres";


CREATE SEQUENCE IF NOT EXISTS "public"."tools_tool_id_seq"
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE "public"."tools_tool_id_seq" OWNER TO "postgres";


ALTER SEQUENCE "public"."tools_tool_id_seq" OWNED BY "public"."tools"."tool_id";



ALTER TABLE ONLY "public"."chats" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."chats_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."endpoint_rate_limits" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."endpoint_rate_limits_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."file_messages" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."file_messages_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."server_settings" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."server_settings_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."tier_rate_limits" ALTER COLUMN "id" SET DEFAULT "nextval"('"public"."tier_rate_limits_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."tools" ALTER COLUMN "tool_id" SET DEFAULT "nextval"('"public"."tools_tool_id_seq"'::"regclass");



ALTER TABLE ONLY "public"."chats"
    ADD CONSTRAINT "chats_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."checkpoint_blobs"
    ADD CONSTRAINT "checkpoint_blobs_pkey" PRIMARY KEY ("thread_id", "checkpoint_ns", "channel", "version");



ALTER TABLE ONLY "public"."checkpoint_migrations"
    ADD CONSTRAINT "checkpoint_migrations_pkey" PRIMARY KEY ("v");



ALTER TABLE ONLY "public"."checkpoint_writes"
    ADD CONSTRAINT "checkpoint_writes_pkey" PRIMARY KEY ("thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx");



ALTER TABLE ONLY "public"."checkpoints"
    ADD CONSTRAINT "checkpoints_pkey" PRIMARY KEY ("thread_id", "checkpoint_ns", "checkpoint_id");



ALTER TABLE ONLY "public"."cron_prompts"
    ADD CONSTRAINT "cron_prompts_pkey" PRIMARY KEY ("id", "chat_id");



ALTER TABLE ONLY "public"."endpoint_rate_limits"
    ADD CONSTRAINT "endpoint_rate_limits_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."file_messages"
    ADD CONSTRAINT "file_messages_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."server_settings"
    ADD CONSTRAINT "server_settings_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."store_migrations"
    ADD CONSTRAINT "store_migrations_pkey" PRIMARY KEY ("v");



ALTER TABLE ONLY "public"."store"
    ADD CONSTRAINT "store_pkey" PRIMARY KEY ("prefix", "key");



ALTER TABLE ONLY "public"."stt_files"
    ADD CONSTRAINT "stt_files_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."threads"
    ADD CONSTRAINT "threads_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tier_rate_limits"
    ADD CONSTRAINT "tier_rate_limits_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."tools"
    ADD CONSTRAINT "tools_pkey" PRIMARY KEY ("tool_id");



ALTER TABLE ONLY "public"."chats"
    ADD CONSTRAINT "unique_chat_id" UNIQUE ("chat_id");



ALTER TABLE ONLY "public"."chats"
    ADD CONSTRAINT "unique_user_name" UNIQUE ("user_name");



CREATE INDEX "checkpoint_blobs_thread_id_idx" ON "public"."checkpoint_blobs" USING "btree" ("thread_id");



CREATE INDEX "checkpoint_writes_thread_id_idx" ON "public"."checkpoint_writes" USING "btree" ("thread_id");



CREATE INDEX "checkpoints_thread_id_idx" ON "public"."checkpoints" USING "btree" ("thread_id");



CREATE INDEX "idx_chats_last_message_time" ON "public"."chats" USING "btree" ("last_message_time");



CREATE INDEX "idx_chats_usage" ON "public"."chats" USING "btree" ("daily_usage", "monthly_usage");



CREATE INDEX "idx_file_messages_chat_message" ON "public"."file_messages" USING "btree" ("chat_id", "message_id");



CREATE INDEX "idx_store_expires_at" ON "public"."store" USING "btree" ("expires_at") WHERE ("expires_at" IS NOT NULL);



CREATE INDEX "idx_stt_files_chat_id" ON "public"."stt_files" USING "btree" ("chat_id");



CREATE INDEX "idx_stt_files_created_at" ON "public"."stt_files" USING "btree" ("created_at");



CREATE INDEX "idx_stt_files_status" ON "public"."stt_files" USING "btree" ("status");



CREATE INDEX "store_prefix_idx" ON "public"."store" USING "btree" ("prefix" "text_pattern_ops");



CREATE OR REPLACE TRIGGER "trg_update_cron_prompts_updated_at" BEFORE UPDATE ON "public"."cron_prompts" FOR EACH ROW EXECUTE FUNCTION "public"."update_cron_prompts_updated_at"();



CREATE OR REPLACE TRIGGER "trigger_update_stt_files_updated_at" BEFORE UPDATE ON "public"."stt_files" FOR EACH ROW EXECUTE FUNCTION "public"."update_stt_files_updated_at"();



ALTER TABLE ONLY "public"."file_messages"
    ADD CONSTRAINT "file_messages_db_thread_id_fkey" FOREIGN KEY ("db_thread_id") REFERENCES "public"."threads"("id");



ALTER TABLE ONLY "public"."file_messages"
    ADD CONSTRAINT "fk_file_messages_chats" FOREIGN KEY ("chat_id") REFERENCES "public"."chats"("chat_id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."threads"
    ADD CONSTRAINT "fk_threads_user" FOREIGN KEY ("user_id") REFERENCES "public"."chats"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."stt_files"
    ADD CONSTRAINT "stt_files_db_thread_id_fkey" FOREIGN KEY ("db_thread_id") REFERENCES "public"."threads"("id");



ALTER TABLE "public"."chats" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."checkpoint_blobs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."checkpoint_migrations" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."checkpoint_writes" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."checkpoints" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."cron_prompts" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."endpoint_rate_limits" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."file_messages" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."server_settings" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."store" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."store_migrations" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."stt_files" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."threads" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."tier_rate_limits" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."tools" ENABLE ROW LEVEL SECURITY;




ALTER PUBLICATION "supabase_realtime" OWNER TO "postgres";








GRANT USAGE ON SCHEMA "public" TO "postgres";
GRANT USAGE ON SCHEMA "public" TO "anon";
GRANT USAGE ON SCHEMA "public" TO "authenticated";
GRANT USAGE ON SCHEMA "public" TO "service_role";















































































































































































































GRANT ALL ON FUNCTION "public"."call_process_message"("p_prompt_text" "text", "p_chat_id" bigint, "p_db_thread_id" "text", "p_message_id" "text", "p_file_url" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."call_process_message"("p_prompt_text" "text", "p_chat_id" bigint, "p_db_thread_id" "text", "p_message_id" "text", "p_file_url" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."call_process_message"("p_prompt_text" "text", "p_chat_id" bigint, "p_db_thread_id" "text", "p_message_id" "text", "p_file_url" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."check_tool_access"("chat_id_input" bigint, "tool_name_input" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."check_tool_access"("chat_id_input" bigint, "tool_name_input" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."check_tool_access"("chat_id_input" bigint, "tool_name_input" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."clear_user_dialog"("p_chat_id" bigint, "p_thread_id" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."clear_user_dialog"("p_chat_id" bigint, "p_thread_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."clear_user_dialog"("p_chat_id" bigint, "p_thread_id" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."clear_user_memory"("p_chat_id" bigint, "p_thread_id" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."clear_user_memory"("p_chat_id" bigint, "p_thread_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."clear_user_memory"("p_chat_id" bigint, "p_thread_id" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."create_cron_prompt_job"("p_chat_id" bigint, "p_prompt_text" "text", "p_jobname" "text", "p_schedule" "text", "p_db_thread_id" "text", "p_message_id" "text", "p_file_url" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."create_cron_prompt_job"("p_chat_id" bigint, "p_prompt_text" "text", "p_jobname" "text", "p_schedule" "text", "p_db_thread_id" "text", "p_message_id" "text", "p_file_url" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."create_cron_prompt_job"("p_chat_id" bigint, "p_prompt_text" "text", "p_jobname" "text", "p_schedule" "text", "p_db_thread_id" "text", "p_message_id" "text", "p_file_url" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."delete_cron_prompt"("p_id" "text", "p_chat_id" bigint) TO "anon";
GRANT ALL ON FUNCTION "public"."delete_cron_prompt"("p_id" "text", "p_chat_id" bigint) TO "authenticated";
GRANT ALL ON FUNCTION "public"."delete_cron_prompt"("p_id" "text", "p_chat_id" bigint) TO "service_role";



GRANT ALL ON FUNCTION "public"."delete_user"("p_chat_id" bigint, "p_user_name" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."delete_user"("p_chat_id" bigint, "p_user_name" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."delete_user"("p_chat_id" bigint, "p_user_name" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."get_allowed_llms"("p_chat_id" bigint) TO "anon";
GRANT ALL ON FUNCTION "public"."get_allowed_llms"("p_chat_id" bigint) TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_allowed_llms"("p_chat_id" bigint) TO "service_role";



GRANT ALL ON FUNCTION "public"."get_available_tools"("p_chat_id" bigint) TO "anon";
GRANT ALL ON FUNCTION "public"."get_available_tools"("p_chat_id" bigint) TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_available_tools"("p_chat_id" bigint) TO "service_role";



GRANT ALL ON FUNCTION "public"."get_user_limits"("p_chat_id" bigint) TO "anon";
GRANT ALL ON FUNCTION "public"."get_user_limits"("p_chat_id" bigint) TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_user_limits"("p_chat_id" bigint) TO "service_role";



GRANT ALL ON FUNCTION "public"."get_user_profile_and_tools"("p_chat_id" bigint) TO "anon";
GRANT ALL ON FUNCTION "public"."get_user_profile_and_tools"("p_chat_id" bigint) TO "authenticated";
GRANT ALL ON FUNCTION "public"."get_user_profile_and_tools"("p_chat_id" bigint) TO "service_role";



GRANT ALL ON FUNCTION "public"."list_cron_prompts_by_chat"("p_chat_id" bigint) TO "anon";
GRANT ALL ON FUNCTION "public"."list_cron_prompts_by_chat"("p_chat_id" bigint) TO "authenticated";
GRANT ALL ON FUNCTION "public"."list_cron_prompts_by_chat"("p_chat_id" bigint) TO "service_role";



GRANT ALL ON FUNCTION "public"."nanoid"("size" integer, "alphabet" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."nanoid"("size" integer, "alphabet" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."nanoid"("size" integer, "alphabet" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."reset_daily_usage"() TO "anon";
GRANT ALL ON FUNCTION "public"."reset_daily_usage"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."reset_daily_usage"() TO "service_role";



GRANT ALL ON FUNCTION "public"."reset_monthly_usage"() TO "anon";
GRANT ALL ON FUNCTION "public"."reset_monthly_usage"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."reset_monthly_usage"() TO "service_role";



GRANT ALL ON FUNCTION "public"."set_service_maintenance"("p_enabled" boolean) TO "anon";
GRANT ALL ON FUNCTION "public"."set_service_maintenance"("p_enabled" boolean) TO "authenticated";
GRANT ALL ON FUNCTION "public"."set_service_maintenance"("p_enabled" boolean) TO "service_role";



GRANT ALL ON FUNCTION "public"."set_user_llm"("p_chat_id" bigint, "p_llm_choice" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."set_user_llm"("p_chat_id" bigint, "p_llm_choice" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."set_user_llm"("p_chat_id" bigint, "p_llm_choice" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."update_cron_prompt"("p_id" "text", "p_chat_id" bigint, "p_prompt_text" "text", "p_schedule" "text", "p_db_thread_id" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."update_cron_prompt"("p_id" "text", "p_chat_id" bigint, "p_prompt_text" "text", "p_schedule" "text", "p_db_thread_id" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_cron_prompt"("p_id" "text", "p_chat_id" bigint, "p_prompt_text" "text", "p_schedule" "text", "p_db_thread_id" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."update_cron_prompts_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_cron_prompts_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_cron_prompts_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."update_stt_files_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_stt_files_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_stt_files_updated_at"() TO "service_role";



GRANT ALL ON FUNCTION "public"."user_auth_checks"("p_chat_id" bigint, "p_user_name" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."user_auth_checks"("p_chat_id" bigint, "p_user_name" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."user_auth_checks"("p_chat_id" bigint, "p_user_name" "text") TO "service_role";

































GRANT ALL ON TABLE "public"."chats" TO "anon";
GRANT ALL ON TABLE "public"."chats" TO "authenticated";
GRANT ALL ON TABLE "public"."chats" TO "service_role";



GRANT ALL ON SEQUENCE "public"."chats_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."chats_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."chats_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."checkpoint_blobs" TO "anon";
GRANT ALL ON TABLE "public"."checkpoint_blobs" TO "authenticated";
GRANT ALL ON TABLE "public"."checkpoint_blobs" TO "service_role";



GRANT ALL ON TABLE "public"."checkpoint_migrations" TO "anon";
GRANT ALL ON TABLE "public"."checkpoint_migrations" TO "authenticated";
GRANT ALL ON TABLE "public"."checkpoint_migrations" TO "service_role";



GRANT ALL ON TABLE "public"."checkpoint_writes" TO "anon";
GRANT ALL ON TABLE "public"."checkpoint_writes" TO "authenticated";
GRANT ALL ON TABLE "public"."checkpoint_writes" TO "service_role";



GRANT ALL ON TABLE "public"."checkpoints" TO "anon";
GRANT ALL ON TABLE "public"."checkpoints" TO "authenticated";
GRANT ALL ON TABLE "public"."checkpoints" TO "service_role";



GRANT ALL ON TABLE "public"."cron_prompts" TO "anon";
GRANT ALL ON TABLE "public"."cron_prompts" TO "authenticated";
GRANT ALL ON TABLE "public"."cron_prompts" TO "service_role";



GRANT ALL ON TABLE "public"."endpoint_rate_limits" TO "anon";
GRANT ALL ON TABLE "public"."endpoint_rate_limits" TO "authenticated";
GRANT ALL ON TABLE "public"."endpoint_rate_limits" TO "service_role";



GRANT ALL ON SEQUENCE "public"."endpoint_rate_limits_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."endpoint_rate_limits_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."endpoint_rate_limits_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."file_messages" TO "anon";
GRANT ALL ON TABLE "public"."file_messages" TO "authenticated";
GRANT ALL ON TABLE "public"."file_messages" TO "service_role";



GRANT ALL ON SEQUENCE "public"."file_messages_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."file_messages_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."file_messages_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."server_settings" TO "anon";
GRANT ALL ON TABLE "public"."server_settings" TO "authenticated";
GRANT ALL ON TABLE "public"."server_settings" TO "service_role";



GRANT ALL ON SEQUENCE "public"."server_settings_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."server_settings_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."server_settings_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."store" TO "anon";
GRANT ALL ON TABLE "public"."store" TO "authenticated";
GRANT ALL ON TABLE "public"."store" TO "service_role";



GRANT ALL ON TABLE "public"."store_migrations" TO "anon";
GRANT ALL ON TABLE "public"."store_migrations" TO "authenticated";
GRANT ALL ON TABLE "public"."store_migrations" TO "service_role";



GRANT ALL ON TABLE "public"."stt_files" TO "anon";
GRANT ALL ON TABLE "public"."stt_files" TO "authenticated";
GRANT ALL ON TABLE "public"."stt_files" TO "service_role";



GRANT ALL ON TABLE "public"."threads" TO "anon";
GRANT ALL ON TABLE "public"."threads" TO "authenticated";
GRANT ALL ON TABLE "public"."threads" TO "service_role";



GRANT ALL ON TABLE "public"."tier_rate_limits" TO "anon";
GRANT ALL ON TABLE "public"."tier_rate_limits" TO "authenticated";
GRANT ALL ON TABLE "public"."tier_rate_limits" TO "service_role";



GRANT ALL ON SEQUENCE "public"."tier_rate_limits_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."tier_rate_limits_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."tier_rate_limits_id_seq" TO "service_role";



GRANT ALL ON TABLE "public"."tools" TO "anon";
GRANT ALL ON TABLE "public"."tools" TO "authenticated";
GRANT ALL ON TABLE "public"."tools" TO "service_role";



GRANT ALL ON SEQUENCE "public"."tools_tool_id_seq" TO "anon";
GRANT ALL ON SEQUENCE "public"."tools_tool_id_seq" TO "authenticated";
GRANT ALL ON SEQUENCE "public"."tools_tool_id_seq" TO "service_role";









ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES  TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES  TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES  TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES  TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS  TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS  TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS  TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS  TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES  TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES  TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES  TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES  TO "service_role";







ALTER ROLE service_role SET search_path = "$user", public, extensions;























RESET ALL;
