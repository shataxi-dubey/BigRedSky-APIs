Celery + Redis for resume chunking and parsing 

  How Celery + Redis work together in this app
                                                                                                                                    
  Three separate processes must all be running at the same time:
                                                                                                                                    
  ┌──────────────────┐   POST /resume/parse   ┌──────────────────┐
  │   FastAPI app    │ ─────────────────────▶ │   Redis (broker) │                                                                  
  │  (web server)    │   dispatches 2 tasks   │   stores task    │                                                                  
  └──────────────────┘                        │   in a queue     │                                                                  
                                              └────────┬─────────┘                                                                  
                                                       │ picks up task                                                              
                                              ┌────────▼─────────┐
                                              │  Celery worker   │                                                                  
                                              │  runs parse_resume│                                                                 
                                              │  runs chunk_resume│
                                              └──────────────────┘                                                                  
                                                            
  - Redis = the message bus. FastAPI puts task messages in, the Celery worker reads them out.                                       
  - Celery worker = a separate Python process that executes parse_resume and chunk_resume in the background.
  - FastAPI = the HTTP server. It does NOT run the tasks — it only dispatches them.                                                 
                                                                                                                                    
  ---                                                                                                                               
  For local development (recommended — easiest)                                                                                     
                                                                                                                                    
  You only need Docker for Redis. Run the other two processes locally in separate terminals.
                                                                                                                                    
  Step 1 — create your .env (one time):                                                                                             
  cp docs/example.env .env                                                                                                          
  # Edit .env — at minimum set:                                                                                                     
  # REDIS_PASSWORD=yourpassword                             
  # OPENAI_API_KEY=sk-...                                                                                                           
  
  Step 2 — start Redis only via Docker:                                                                                             
  docker compose up redis -d                                
                                                                                                                                    
  Step 3 — start FastAPI (terminal 1):                      
  make run                                                                                                                          
  
  Step 4 — start the Celery worker (terminal 2):                                                                                    
  uv run celery -A app.tasks.celery_main.celery_app worker --loglevel=info
                                                                          
  You should see the worker register your tasks:                                                                                    
  [tasks]                                                                                                                           
    . parse_resume                                                                                                                  
    . chunk_resume                                                                                                                  
                                                                                                                                    
  ---