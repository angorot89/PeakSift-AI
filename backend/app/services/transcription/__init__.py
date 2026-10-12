"""Speech-to-text providers behind one contract.

Everything outside this package consumes ``ProviderTranscriptionResult`` only; provider
SDK objects (faster-whisper, OpenAI) never leave their own module.
"""
