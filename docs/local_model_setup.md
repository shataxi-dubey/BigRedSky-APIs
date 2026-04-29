# Local Model Setup Guide

This guide shows how to use your local LM Studio model instead of OpenAI and DuckDuckGo instead of Tavily.

## Configuration

Add these settings to your `.env` file:

```env
# Model Configuration
USE_LOCAL_MODEL=true
LOCAL_MODEL_URL=http://127.0.0.1:1234

# Search Provider Configuration
SEARCH_PROVIDER=duckduckgo  # "duckduckgo" or "tavily"
DUCKDUCKGO_MAX_RESULTS=10

# OpenAI Configuration (used when USE_LOCAL_MODEL=false)
OPENAI_API_KEY=your_openai_api_key_here

# Tavily Configuration (used when SEARCH_PROVIDER=tavily)
TAVILY_API_KEY=your_tavily_api_key_here
```

## Setup Steps

### 1. Start LM Studio
- Open LM Studio
- Load your preferred model
- Start the local server on `http://127.0.0.1:1234`

### 2. Configure Environment
Create a `.env` file in the project root:

```env
# Core Settings
LOG_LEVEL=DEBUG
ENVIRONMENT=development
HOST=0.0.0.0
PORT=8002

# Model Configuration
USE_LOCAL_MODEL=true
LOCAL_MODEL_URL=http://127.0.0.1:1234

# Search Provider Configuration
SEARCH_PROVIDER=duckduckgo
DUCKDUCKGO_MAX_RESULTS=10

# Optional: Tavily (if you want to switch back)
TAVILY_API_KEY=your_tavily_api_key_here

# Optional: Langfuse for observability
LANGFUSE_HOST=https://cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=your_langfuse_public_key
LANGFUSE_SECRET_KEY=your_langfuse_secret_key
```

### 3. Run the Application
```bash
# Install dependencies
uv sync

# Start the application
make run-dev
```

### 4. Test the Setup
```bash
# Test web search with local model and DuckDuckGo
curl "http://localhost:8002/api/v1/chat/websearch?question=What%20is%20Python%20programming&thread_id=123"
```

## Switching Between Models and Search Providers

### Use Local Model + DuckDuckGo (Free Setup)
```env
USE_LOCAL_MODEL=true
LOCAL_MODEL_URL=http://127.0.0.1:1234
SEARCH_PROVIDER=duckduckgo
```

### Use OpenAI + Tavily (Paid Setup)
```env
USE_LOCAL_MODEL=false
OPENAI_API_KEY=your_openai_api_key_here
SEARCH_PROVIDER=tavily
TAVILY_API_KEY=your_tavily_api_key_here
```

### Mix and Match
```env
# Local model with Tavily search
USE_LOCAL_MODEL=true
LOCAL_MODEL_URL=http://127.0.0.1:1234
SEARCH_PROVIDER=tavily
TAVILY_API_KEY=your_tavily_api_key_here

# OpenAI with DuckDuckGo search
USE_LOCAL_MODEL=false
OPENAI_API_KEY=your_openai_api_key_here
SEARCH_PROVIDER=duckduckgo
```

## Benefits of Free Setup (Local Model + DuckDuckGo)

1. **No API Costs**: Completely free to use
2. **Privacy**: All processing happens locally
3. **No Rate Limits**: DuckDuckGo has no API limits
4. **Customizable**: Use any model supported by LM Studio
5. **Offline**: Works without internet connection (except for web search)
6. **Fast**: No network latency for model inference

## Search Provider Comparison

| Feature | DuckDuckGo | Tavily |
|---------|------------|--------|
| Cost | Free | Free tier + paid |
| Rate Limits | None | 1,000/month free |
| API Key Required | No | Yes |
| Search Quality | Good | Excellent |
| Structured Results | Basic | Advanced |
| Content Extraction | Limited | Full |

## Troubleshooting

### Connection Issues
- Ensure LM Studio is running on the correct port
- Check that the model is loaded and ready
- Verify the URL in `LOCAL_MODEL_URL`

### Search Issues
- DuckDuckGo may occasionally have rate limiting
- Try switching to Tavily if you need more reliable search
- Check internet connection for web search functionality

### Model Performance
- Local models may be slower than OpenAI
- Adjust model parameters in LM Studio for better performance
- Consider using smaller, faster models for development

### Structured Output
- Local models may not handle structured output as well as OpenAI
- The system includes fallback parsing for local models
- For complex structured tasks, consider using OpenAI 