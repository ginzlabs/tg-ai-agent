
-- Schedule daily reset at midnight UTC
SELECT cron.schedule(
  'reset_daily_usage_job',
  '0 0 * * *',
  $$SELECT public.reset_daily_usage();$$
);

-- Schedule monthly reset on the 1st at midnight UTC
SELECT cron.schedule(
  'reset_monthly_usage_job',
  '0 0 1 * *',
  $$SELECT public.reset_monthly_usage();$$
);


INSERT INTO public.endpoint_rate_limits VALUES (4, 'process_message', 100, 60);
INSERT INTO public.endpoint_rate_limits VALUES (3, 'delete_user', 100, 60);
INSERT INTO public.endpoint_rate_limits VALUES (2, 'create_user', 100, 60);
INSERT INTO public.endpoint_rate_limits VALUES (1, 'send_message_to_user', 100, 60);
INSERT INTO public.endpoint_rate_limits VALUES (5, 'check_user', 100, 60);


INSERT INTO public.tier_rate_limits VALUES (1, 1, 5, 100, 1000, 2);
INSERT INTO public.tier_rate_limits VALUES (2, 2, 3, 500, 5000, 4);
INSERT INTO public.tier_rate_limits VALUES (3, 3, 1, 1000, 10000, 8);

INSERT INTO public.tools VALUES (5, 'manage_users', 'Admin-only tool to check, create, delete, or update users. Verifies the calling user has admin privileges.', 3, '{}', '🛠️ Manage Users');
INSERT INTO public.tools VALUES (4, 'generate_market_report', 'Generate a market report of bond yields.', 3, '{"FT_URL": "https://markets.ft.com/data/bonds"}', '📈 Market Report');
INSERT INTO public.tools VALUES (3, 'test_tool', 'A simple human-in-the-loop (HITL) test tool that logs an input message and returns a response. Useful for testing and debugging.', 1, '{}', '🧪 Test Tool');
INSERT INTO public.tools VALUES (6, 'manage_cron_prompts', 'Manage scheduled prompt jobs (create, list, update, or delete cron prompts)', 1, '{}', '⏰ Scheduled Tasks');
INSERT INTO public.tools VALUES (7, 'stt_tool', 'Record or send voice messages, and the bot will transcribe and respond. Attach an audio file, and you''ll get a transcript plus a summary.', 1, '{}', '🗣️Speech-to-text');
INSERT INTO public.tools VALUES (1, 'search_tavily', 'Search for general web results using the Tavily search engine. Useful for answering questions about current events.', 1, '{}', '📚 Web search');
INSERT INTO public.tools VALUES (2, 'upsert_memory', 'Upsert a memory in the database. Updates existing memory if ID is provided; otherwise, inserts a new one.', 1, '{}', '💾 Long term memory');


INSERT INTO storage.buckets VALUES ('stt_files', 'stt_files', NULL, '2025-03-21 19:14:58.431984+00', '2025-03-21 19:14:58.431984+00', true, false, NULL, NULL, NULL);
INSERT INTO storage.buckets VALUES ('reports', 'reports', NULL, '2025-03-28 13:55:57.218501+00', '2025-03-28 13:55:57.218501+00', true, false, NULL, NULL, NULL);
