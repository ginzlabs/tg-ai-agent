"""
Configuration settings for the backend server.
"""

# Rate limiting configuration
RATE_LIMITS = {
    # Format: "endpoint_name": "requests/seconds"
    "transcribe": "100/minute",
    "generate_report": "100/minute",
    "stt": "100/minute",
    "default": "100/minute", 
}

# Logging configuration
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DEFAULT_LOG_LEVEL = "INFO"

# API configuration
API_VERSION = "v1"
API_PREFIX = f"/api/{API_VERSION}"

# Task Manager configuration
MAX_CONCURRENT_TASKS = 10
TASK_TIMEOUT = 3600  # 1 hour in seconds
TASK_RETENTION_MINUTES = 5  # How long to keep completed tasks

# Concurrency limits per task type
TASK_CONCURRENCY_LIMITS = {
    "transcription": 2,  # Allow 2 concurrent transcriptions
    "report": 3,        # Allow 3 concurrent report generations
    "default": 5        # Default limit for other tasks
}

# Queue processing interval in seconds
QUEUE_CHECK_INTERVAL = 1 

# Speech-to-Text summary text configurations
STT_SUMMARY_TEXTS = {
    "system_prompt": """
            You are a professional meeting summarizer. Analyze the provided transcript and generate a clear and concise summary.

            The summary should primarily include the substantive statements made by each participant. Include only those statements that carry meaningful information: key decisions, proposals, important remarks, shared data, or expressed concerns. Ignore greetings, procedural comments, and simple acknowledgments unless they reflect a reached consensus.

            Your result must be formatted as valid JSON with the following fields:
            - summary: A brief summary of the meeting (1–3 paragraphs) that includes a structured overview of each participant’s key statements.
            - key_points: A list of main decisions, actions, and key conclusions from the meeting in bullet-point format.
            - sentiment: The overall tone of the discussion (choose one: positive, neutral, negative).

            Be objective, focus on clarity and relevance, eliminate repetition, and do not add anything that was not explicitly said or is not essential.

            Pay special attention to the following technical terms that may be distorted in the transcript: {complex_words}
            If similar-sounding or contextually similar words appear in the text that could be speech recognition errors, replace them with the correct terms from the list above. Take into account the discussion context and the logical structure of the statements.
            """,
    "summary": {
        "title": "Summary",
        "key_points_title": "Key Points",
        "full_transcript_title": "Full Transcript"
    },
    "speaker": {
        "label": "Speaker: {}"  # Format string for speaker labels
    },
    "disclaimer": "⚠️ This transcript and summary were generated using artificial intelligence. Inaccuracies and errors are possible.",
    "complex_words": [
        "tops",
        "combed sliver",
        "spinning",
        "spinning machine",
        "twisting machine",
        "yarn",
    ]
}
