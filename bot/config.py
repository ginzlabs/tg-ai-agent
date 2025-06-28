# Application configuration settings

# Task processing settings
ENABLE_TASK_QUEUING = True  # If True, queue multiple tasks; if False, only allow one at a time
TASK_RETENTION_MINUTES = 30  # How long to keep completed tasks in memory
TASK_CONCURRENCY_LIMITS = 1  # Maximum number of tasks that can run simultaneously per user
QUEUE_CHECK_INTERVAL = 0.5  # How often to check queues (in seconds)

# Telegram message templates
PROCESSING_MESSAGE = "⏳ _Processing your message. This will take a few moments..._"
TASK_ALREADY_RUNNING_MESSAGE = "Sorry, your previous request is still processing and we only allow one at a time. If you wish to cancel, press the button below and then submit a new request."
TASK_CANCELLED_MESSAGE = "Your previous task has been cancelled. You can now submit a new request."
TASK_COMPLETED_MESSAGE = "✅ Message processing complete. This simulates a long-running task."
TASK_CANCELLED_BY_USER_MESSAGE = "Task was cancelled by user."
REJECTED_REQUEST_MESSAGE = "This request could not be processed as previous request was already running. You can now submit a new request for processing." 

# STT specific messages
STT_PROCESSING_MESSAGE = "🎙️ _Processing your audio for transcription..._"
STT_SUBMITTED_MESSAGE = "✅ Your audio has been submitted for transcription. You will receive the results shortly."
STT_FAILED_MESSAGE = "❌ Error processing your audio file. Please try again later."

# Other messages
EMPTY_MESSAGE_DEFAULT = "No text"
