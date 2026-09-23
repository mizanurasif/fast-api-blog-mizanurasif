# FastAPI Blog

A full-stack blogging platform built with **FastAPI**, **async SQLAlchemy 2.0** and **PostgreSQL** — with JWT authentication, Reddit-style voting, S3 image uploads, transactional password-reset email, Alembic migrations and an async test suite.

The backend is a clean JSON API (`/api/...`, fully documented at `/docs`), and the frontend is server-rendered Jinja2 + vanilla ES modules that consumes that same API. No frontend framework, no build step.

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Alembic](https://img.shields.io/badge/Alembic-migrations-6BA81E)
![AWS S3](https://img.shields.io/badge/AWS-S3-FF9900?logo=amazons3&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-blue)

---

## Table of contents

- [What this project demonstrates](#what-this-project-demonstrates)
- [Features](#features)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Engineering notes](#engineering-notes)
- [Getting started](#getting-started)
- [Configuration reference](#configuration-reference)
- [Setting up AWS S3](#setting-up-aws-s3)
- [Setting up email](#setting-up-email)
- [Database migrations](#database-migrations)
- [Seeding demo data](#seeding-demo-data)
- [Running the tests](#running-the-tests)
- [Docker](#docker)
- [API reference](#api-reference)
- [License](#license)

---

## What this project demonstrates


| Area                     | What's in here                                                                                                                                                                     |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Async Python**         | Every request path is`async` end to end — async SQLAlchemy sessions, async SMTP, async HTTP tests. No blocking call is left on the event loop.                                    |
| **Relational modelling** | One-to-many (user→posts), a voting table with a composite`UNIQUE` constraint and a `CHECK` constraint, and a computed aggregate exposed as a model attribute.                     |
| **Query engineering**    | Vote totals computed in SQL via a correlated subquery, so posts can be*sorted* by score in the database instead of in Python. Eager loading (`selectinload`) to avoid N+1 queries. |
| **Schema evolution**     | Alembic migration history, including a real SQLite → PostgreSQL migration.                                                                                                        |
| **Authentication**       | OAuth2 password flow, JWT access tokens, Argon2 password hashing, and single-use hashed password-reset tokens with expiry.                                                         |
| **Cloud storage**        | Profile pictures normalised with Pillow and uploaded to AWS S3; blocking boto3 calls pushed to a threadpool.                                                                       |
| **Testing**              | Async pytest suite with per-test transaction rollback for isolation, and`moto` mocking S3 so tests never touch AWS.                                                                |
| **Deployment**           | Multi-stage Dockerfile using`uv`, 12-factor config via `pydantic-settings`, security-headers middleware, and a `/health` endpoint.                                                 |

---

## Features

### Accounts & authentication

- Register with unique, case-insensitive username and email
- Login via OAuth2 password flow returning a JWT bearer token
- Argon2 password hashing (`pwdlib`)
- **Forgot password** — emails a single-use reset link; only the SHA-256 *hash* of the token is stored, and the token expires after 60 minutes
- Change password while logged in
- Update username/email, delete account (cascades to posts and votes)

### Posts

- Full CRUD via the API, with ownership checks
- Create/edit/delete from the UI through Bootstrap modals
- Pagination (`skip`/`limit`) with an AJAX "Load More" button
- Per-author feed at `/users/{id}/posts`

### Voting

- Upvote / downvote, one vote per user per post (enforced by a database `UNIQUE` constraint, not application logic)
- Clicking the same arrow twice removes your vote; clicking the other arrow flips it
- Live score updates without a page reload
- **Top Posts** page ranking posts by net score, sorted in SQL
- Per-user reputation stats: upvotes/downvotes received and given

### Media

- Profile picture upload — EXIF-rotated, centre-cropped to 300×300 and re-encoded as optimised JPEG
- Stored in S3 under `profile_pics/`, served directly from the bucket
- Configurable max upload size (default 5 MB); users without a picture fall back to a bundled default

### Frontend

- Server-rendered Jinja2 templates with a Bootstrap 5 layout
- Light / dark / auto theme toggle persisted to `localStorage`
- Vanilla ES modules (`auth.js`, `votes.js`, `utils.js`) — no bundler
- Custom error pages and friendly validation messages

---

## Tech stack


| Layer               | Choice                                                     |
| ------------------- | ---------------------------------------------------------- |
| Web framework       | FastAPI                                                    |
| ORM                 | SQLAlchemy 2.0 (async, typed`Mapped[]` declarative models) |
| Database            | PostgreSQL via`psycopg` 3 (async driver)                   |
| Migrations          | Alembic (async`env.py`)                                    |
| Auth                | `PyJWT` + `pwdlib[argon2]`, OAuth2 password bearer         |
| Validation / config | Pydantic v2 +`pydantic-settings`                           |
| Templates           | Jinja2                                                     |
| Object storage      | AWS S3 via`boto3`                                          |
| Email               | `aiosmtplib`, HTML + plain-text multipart                  |
| Images              | Pillow                                                     |
| Tests               | `pytest`, `anyio`, `httpx.AsyncClient`, `moto`             |
| Packaging           | `uv`                                                       |
| Container           | Docker (multi-stage)                                       |

---

## Project structure

```
.
├── main.py              # App setup, middleware, HTML page routes, exception handlers
├── models.py            # SQLAlchemy models: User, Post, Vote, PasswordResetToken
├── schemas.py           # Pydantic request/response models
├── database.py          # Async engine, session factory, get_db dependency
├── auth.py              # Password hashing, JWT create/verify, get_current_user dependency
├── config.py            # Settings loaded from .env (pydantic-settings)
├── email_utils.py       # Async SMTP sending + password-reset email
├── image_utils.py       # Pillow processing + S3 upload/delete
├── populate_db.py       # Seed script: demo users, posts, votes, profile pictures
├── routers/
│   ├── posts.py         # /api/posts — CRUD, pagination, voting
│   └── users.py         # /api/users — auth, profile, password reset, picture, stats
├── templates/           # Jinja2 pages + templates/email/ for HTML mail
├── static/
│   ├── css/main.css
│   └── js/              # auth.js, votes.js, utils.js
├── alembic/versions/    # Migration history
├── tests/               # conftest.py fixtures + API tests
└── Dockerfile
```

---

## Engineering notes

A few problems in this codebase were more interesting than they first looked.

### 1. Vote score is a SQL expression, not a Python property

The obvious way to compute a post's score is a property:

```python
@property
def score(self) -> int:
    return sum(v.value for v in self.votes)   # don't do this
```

This breaks in two ways. First, touching `self.votes` triggers a lazy load, and in an async app that database I/O has to be awaited — a property can't await, so SQLAlchemy raises `MissingGreenlet`. Second, the value only exists in Python *after* the rows arrive, so the database can't `ORDER BY` it — you'd have to fetch every post just to find the top ten.

Instead the score is declared as a `column_property` holding a correlated subquery:

```python
Post.score = column_property(
    select(func.coalesce(func.sum(Vote.value), 0))
    .where(Vote.post_id == Post.id)
    .correlate_except(Vote)
    .scalar_subquery()
)
```

which compiles into every `SELECT` on posts:

```sql
SELECT posts.id, posts.title, ...,
       (SELECT coalesce(sum(votes.value), 0)
        FROM votes WHERE votes.post_id = posts.id) AS score
FROM posts
ORDER BY score DESC
```

One round trip, no lazy load, and sortable in the database — which is what makes the Top Posts page a one-line `.order_by()`. The `coalesce` matters: `SUM` over zero rows returns `NULL`, not `0`, so a brand-new post would fail `score: int` validation without it.

The trade-off is that the value is a snapshot from load time, so after casting a vote the code explicitly calls `await db.refresh(post, attribute_names=["score"])`. A freshly `INSERT`ed post never went through a `SELECT` at all, so `create_post` refreshes it too.

### 2. Cascade deletes need both halves

`cascade="all, delete-orphan"` is a *Python* instruction — SQLAlchemy loads the children and deletes them one by one. `ondelete="CASCADE"` is a *database* instruction written into the foreign key. Adding `passive_deletes=True` switches the Python side **off** and hands the job to the database, which means the database has to actually have been told to do it — otherwise deleting a post that has votes raises a `ForeignKeyViolation`. This project uses all three together, so deleting a user is a single `DELETE` statement instead of thousands of round trips.

### 3. boto3 is synchronous

`boto3` has no async API, so calling it directly would block the event loop for the duration of an upload. Uploads and deletes are wrapped in `run_in_threadpool(...)`, keeping the server responsive while S3 transfers happen.

### 4. Test isolation via transaction rollback

Each test runs inside a connection-level transaction with `join_transaction_mode="create_savepoint"`, and that transaction is rolled back afterwards. Tests can commit freely and still leave the database pristine — no truncating tables between tests, no ordering dependencies. S3 is faked with `moto`, so the suite runs offline.

### 5. SQLite to PostgreSQL

The project started on SQLite and moved to PostgreSQL once real constraints and aggregate features (`FILTER`, enforced `CHECK`) were needed. The move is captured in the Alembic history rather than a schema reset.

---

## Getting started

### Prerequisites


| Requirement                          | Notes                                                                    |
| ------------------------------------ | ------------------------------------------------------------------------ |
| **Python 3.13+**                     | `requires-python = ">=3.13"`                                             |
| **PostgreSQL 14+**                   | Running locally, or in Docker                                            |
| **[uv](https://docs.astral.sh/uv/)** | Package manager —`pip install uv`, or see the install docs              |
| **AWS S3 bucket**                    | Only needed for profile picture uploads (see[below](#setting-up-aws-s3)) |
| **SMTP server**                      | Only needed for password reset — a local test server works fine         |

### 1. Clone and install

```bash
git clone https://github.com/mizanurasif/Fast-API-Blog.git
cd Fast-API-Blog
uv sync
```

`uv sync` creates `.venv/` and installs everything. Add `--group dev` if you also want the test dependencies.

### 2. Create the database

```bash
psql -U postgres -c "CREATE USER bloguser WITH PASSWORD 'blogpass';"
psql -U postgres -c "CREATE DATABASE blog OWNER bloguser;"
psql -U postgres -c "CREATE DATABASE test_blog OWNER bloguser;"
```

Or with Docker instead of a local install:

```bash
docker run -d --name blog-postgres \
  -e POSTGRES_USER=bloguser \
  -e POSTGRES_PASSWORD=blogpass \
  -e POSTGRES_DB=blog \
  -p 5432:5432 postgres:16
```

> `test_blog` is the database the test suite uses — it is hardcoded in `tests/conftest.py`. Create it now if you plan to run the tests.

### 3. Configure the environment

Copy the example file and fill it in:

```bash
cp .env.example .env
```

At minimum you need `DATABASE_URL`, `SECRET_KEY` and `S3_BUCKET_NAME`. Generate a real secret key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

The full list of variables is in the [configuration reference](#configuration-reference).

### 4. Run the migrations

```bash
uv run alembic upgrade head
```

This creates every table. Alembic reads `DATABASE_URL` from your `.env` — there is no URL in `alembic.ini`.

### 5. Start the server

```bash
uv run fastapi dev main.py
```


| URL                                                          | What                                            |
| ------------------------------------------------------------ | ----------------------------------------------- |
| [http://localhost:8000](http://localhost:8000)               | The blog                                        |
| [http://localhost:8000/docs](http://localhost:8000/docs)     | Interactive Swagger UI                          |
| [http://localhost:8000/redoc](http://localhost:8000/redoc)   | ReDoc                                           |
| [http://localhost:8000/health](http://localhost:8000/health) | Health check (verifies the database connection) |

Register an account through the UI and you're running.

> **Windows note:** `psycopg`'s async mode cannot use Windows' default `ProactorEventLoop`. The app is fine under `fastapi dev`, but any standalone async script you write against the database needs `asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)`. `populate_db.py` and `tests/conftest.py` already handle this.

---

## Configuration reference

All settings are read from `.env` by `config.py`. Names are case-insensitive.

### Required


| Variable         | Description                                                  | Example                                                 |
| ---------------- | ------------------------------------------------------------ | ------------------------------------------------------- |
| `DATABASE_URL`   | Async PostgreSQL connection string                           | `postgresql+psycopg://bloguser:blogpass@localhost/blog` |
| `SECRET_KEY`     | Key used to sign JWTs — keep it secret, rotate it if leaked | generate with the command above                         |
| `S3_BUCKET_NAME` | Bucket for profile pictures                                  | `my-blog-media`                                         |

### Authentication


| Variable                      | Default | Description                  |
| ----------------------------- | ------- | ---------------------------- |
| `ALGORITHM`                   | `HS256` | JWT signing algorithm        |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30`    | Access token lifetime        |
| `RESET_TOKEN_EXPIRE_MINUTES`  | `60`    | Password-reset link lifetime |

### Storage


| Variable                | Default      | Description                                                   |
| ----------------------- | ------------ | ------------------------------------------------------------- |
| `S3_REGION`             | `eu-north-1` | Bucket region                                                 |
| `S3_ACCESS_KEY_ID`      | —           | IAM access key (omit to use the ambient AWS credential chain) |
| `S3_SECRET_ACCESS_KEY`  | —           | IAM secret key                                                |
| `S3_ENDPOINT_URL`       | —           | Override for MinIO / LocalStack                               |
| `MAX_UPLOAD_SIZE_BYTES` | `5242880`    | Max profile picture size (5 MB)                               |

### Email


| Variable        | Default               | Description                 |
| --------------- | --------------------- | --------------------------- |
| `MAIL_SERVER`   | `localhost`           | SMTP host                   |
| `MAIL_PORT`     | `587`                 | SMTP port                   |
| `MAIL_USERNAME` | `""`                  | SMTP user (blank = no auth) |
| `MAIL_PASSWORD` | `""`                  | SMTP password               |
| `MAIL_FROM`     | `noreply@example.com` | From address                |
| `MAIL_USE_TLS`  | `true`                | Use STARTTLS                |

### Application


| Variable         | Default                 | Description                                 |
| ---------------- | ----------------------- | ------------------------------------------- |
| `POSTS_PER_PAGE` | `10`                    | Page size for feeds and "Load More"         |
| `FRONTEND_URL`   | `http://localhost:8000` | Base URL used to build password-reset links |

---

## Setting up AWS S3

Profile pictures are served directly from the bucket, so those objects must be publicly readable.

1. **Create a bucket** in the S3 console. Note its name and region.
2. **Allow public reads.** Under *Permissions*, turn off "Block all public access", then add this bucket policy (replacing `YOUR-BUCKET-NAME`):

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "PublicReadProfilePics",
         "Effect": "Allow",
         "Principal": "*",
         "Action": "s3:GetObject",
         "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/profile_pics/*"
       }
     ]
   }
   ```

   This grants read access to `profile_pics/` only — nothing else in the bucket is exposed.
3. **Create an IAM user** with programmatic access and a policy allowing `s3:PutObject`, `s3:GetObject` and `s3:DeleteObject` on `arn:aws:s3:::YOUR-BUCKET-NAME/*`. Put its keys in `.env`.
4. **Verify** with the included helper:

   ```bash
   uv run python check_s3.py
   ```

**No AWS account?** Run [MinIO](https://min.io/) locally and point `S3_ENDPOINT_URL` at it:

```bash
docker run -d -p 9000:9000 -p 9001:9001 \
  -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin \
  minio/minio server /data --console-address ":9001"
```

```dotenv
S3_ENDPOINT_URL=http://localhost:9000
S3_ACCESS_KEY_ID=minioadmin
S3_SECRET_ACCESS_KEY=minioadmin
```

The tests need none of this — `moto` fakes S3 entirely.

---

## Setting up email

Password reset is the only feature that sends mail. The flow:

1. User submits their address at `/forgot-password`
2. A 32-byte URL-safe token is generated; **only its SHA-256 hash is stored**, alongside an expiry
3. The raw token is emailed as a link to `{FRONTEND_URL}/reset-password?token=...`
4. On submit, the token is re-hashed and looked up; if it matches and hasn't expired, the password is updated and the token is consumed

The endpoint always returns `202 Accepted`, whether or not the address exists, so it can't be used to enumerate registered users.

### Local development

Catch outgoing mail without sending anything real. Either run Python's built-in debugging server:

```bash
uv run python -m aiosmtpd -n -l localhost:1025
```

```dotenv
MAIL_SERVER=localhost
MAIL_PORT=1025
MAIL_USE_TLS=false
```

...which prints each message to the terminal, or use [MailHog](https://github.com/mailhog/MailHog) for a web inbox at [http://localhost:8025](http://localhost:8025):

```bash
docker run -d -p 1025:1025 -p 8025:8025 mailhog/mailhog
```

### Gmail

Enable 2FA, create an [App Password](https://myaccount.google.com/apppasswords), then:

```dotenv
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=you@gmail.com
MAIL_PASSWORD=your-16-char-app-password
MAIL_FROM=you@gmail.com
MAIL_USE_TLS=true
```

For production, prefer a transactional provider (SendGrid, Mailgun, AWS SES) — same variables, different host.

---

## Database migrations

Alembic reads `DATABASE_URL` from your settings (`alembic/env.py`), so `alembic.ini` holds no credentials.

```bash
# apply everything
uv run alembic upgrade head

# after editing models.py, generate a migration
uv run alembic revision --autogenerate -m "add comments table"

# inspect and roll back
uv run alembic history
uv run alembic current
uv run alembic downgrade -1
```

Always read a generated migration before applying it — autogenerate catches most changes but misses things like column renames (it sees a drop plus an add) and server-side defaults.

---

## Seeding demo data

`populate_db.py` wipes the database and repopulates it with demo users, posts spread over the past few weeks, realistic vote distributions, and profile pictures uploaded from `populate_images/`.

```bash
uv run python populate_db.py
```

> **This deletes all existing rows.** Only run it against a development database. It also needs working S3 credentials, since it uploads the profile pictures through the real upload path.

---

## Running the tests

```bash
uv sync --group dev
uv run pytest
uv run pytest -v                        # verbose
uv run pytest tests/test_posts.py       # one file
```

The suite needs the `test_blog` database from [step 2](#2-create-the-database) to exist — everything else is faked. Tables are created at session start and dropped at the end; each individual test runs in a transaction that is rolled back afterwards, so tests are order-independent and leave nothing behind.

---

## Docker

```bash
docker build -t fastapi-blog .
docker run -p 8000:8000 --env-file .env fastapi-blog
```

Point `DATABASE_URL` at a reachable host — from inside a container, `localhost` is the container itself, so use `host.docker.internal` (Docker Desktop) or a Compose service name.

> **Two things to fix before this builds from a fresh clone:**
>
> 1. `uv.lock` is listed in `.gitignore`, but the Dockerfile's `uv sync --locked` requires it. Remove that line and commit the lockfile — it is what makes installs reproducible.
> 2. The Dockerfile uses `python:3.12-slim` while `pyproject.toml` declares `requires-python = ">=3.13"`. Bump the base image to `python:3.13-slim`.

---

## API reference

Interactive documentation is generated automatically at `/docs`. Authenticated routes expect `Authorization: Bearer <token>`.

### Users — `/api/users`


| Method   | Path                              | Auth | Description                                                      |
| -------- | --------------------------------- | :--: | ---------------------------------------------------------------- |
| `POST`   | ``                                |  —  | Register a new account                                           |
| `POST`   | `/token`                          |  —  | Log in (form-encoded; send the**email** in the `username` field) |
| `GET`    | `/me`                             |  ✓  | Current user                                                     |
| `POST`   | `/forgot-password`                |  —  | Email a password-reset link                                      |
| `POST`   | `/reset-password`                 |  —  | Consume a reset token and set a new password                     |
| `PATCH`  | `/me/password`                    |  ✓  | Change password                                                  |
| `GET`    | `/me/votes?post_ids=1&post_ids=2` |  ✓  | Your votes on the given posts (max 100)                          |
| `GET`    | `/{user_id}`                      |  —  | Public profile                                                   |
| `PATCH`  | `/{user_id}`                      |  ✓  | Update username / email                                          |
| `DELETE` | `/{user_id}`                      |  ✓  | Delete account and all its content                               |
| `GET`    | `/{user_id}/posts`                |  —  | That user's posts, paginated                                     |
| `GET`    | `/{user_id}/vote-stats`           |  —  | Upvotes/downvotes received and given, plus reputation            |
| `PATCH`  | `/{user_id}/picture`              |  ✓  | Upload a profile picture (multipart)                             |
| `DELETE` | `/{user_id}/picture`              |  ✓  | Remove the profile picture                                       |

### Posts — `/api/posts`


| Method   | Path               | Auth | Description                                       |
| -------- | ------------------ | :--: | ------------------------------------------------- |
| `GET`    | `?skip=0&limit=10` |  —  | Paginated feed, newest first                      |
| `POST`   | ``                 |  ✓  | Create a post                                     |
| `GET`    | `/{post_id}`       |  —  | A single post                                     |
| `PUT`    | `/{post_id}`       |  ✓  | Replace a post (owner only)                       |
| `PATCH`  | `/{post_id}`       |  ✓  | Partially update a post (owner only)              |
| `DELETE` | `/{post_id}`       |  ✓  | Delete a post (owner only)                        |
| `POST`   | `/{post_id}/vote`  |  ✓  | Cast`+1`/`-1`; repeating the same value clears it |

### Pages

`/` · `/posts` · `/top-posts` · `/posts/{id}` · `/users/{id}/posts` · `/login` · `/register` · `/account` · `/forgot-password` · `/reset-password` · `/health`

## License

MIT — see [LICENSE](LICENSE).

Built by **MD Mizanur Rahman**.
