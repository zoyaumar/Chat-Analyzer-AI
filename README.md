Chat Analyzer AI – Backend

FastAPI backend with JWT auth, PostgreSQL (Supabase), and messages.

## Stack
- FastAPI, SQLAlchemy, Pydantic v2
- JWT (python-jose), bcrypt (passlib)
- Postgres on Supabase

## Setup
1. Python 3.11+
2. `py -m pip install -r requirements.txt`
3. `.env`:
```

DATABASE\_URL=postgresql://...
SECRET\_KEY=replace\_me

````
4. Run: `uvicorn app.main:app --reload`

## Endpoints
- `POST /users/register` – JSON: `{ "username": "...", "password": "..." }`
- `POST /users/login` – form: `username`, `password` → returns `{ access_token, token_type }`
- `POST /messages/` – JSON: `{ "text": "..." }` (requires `Authorization: Bearer <token>`)
- `GET /messages/` – list messages

## Testing
- Swagger: http://127.0.0.1:8000/docs → Authorize → paste `Bearer <token>`
- Postman:
- Login request saves token with:
 ```js
 pm.environment.set("token", pm.response.json().access_token);
 ```
- Use header: `Authorization: Bearer {{token}}`
