from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text,UniqueConstraint,CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship,column_property
from sqlalchemy import select,func
from database import Base
from config import settings


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    image_file: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        default=None,
    )

    posts: Mapped[list[Post]] = relationship(back_populates="author", cascade="all, delete-orphan")

    reset_tokens: Mapped[list[PasswordResetToken]] = relationship(
            back_populates="user",
            cascade="all, delete-orphan",
        )
    votes: Mapped[list[Vote]] = relationship(back_populates="user", cascade="all, delete-orphan", passive_deletes=True,)

    @property
    def image_path(self) -> str:
        if self.image_file:
            #return f"/media/profile_pics/{self.image_file}"
            return f"https://{settings.s3_bucket_name}.s3.{settings.s3_region}.amazonaws.com/profile_pics/{self.image_file}"
        return "/static/profile_pics/default.png"


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    date_posted: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    author: Mapped[User] = relationship(back_populates="posts")
    # in Post
    votes: Mapped[list[Vote]] = relationship(
    back_populates="post", cascade="all, delete-orphan", passive_deletes=True,)

#   @property
#   def score(self)->int:
#        return sum(v.value for v in self.votes)
#Why i can not use it?
#In a normal (sync) app that's just slow. In your async app it's fatal, because talking to the
#database requires await, and a @property can't await anything. Python has no way to pause inside
#a property and wait for the database. SQLAlchemy notices and throws MissingGreenlet.

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    user: Mapped[User] = relationship(back_populates="reset_tokens")

class Vote(Base):
    __tablename__ = "votes"

    id: Mapped[int] = mapped_column(Integer,primary_key=True,index= True)

    # user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), nullable=False)
    # ondelete="CASCADE" is required, not optional: passive_deletes=True on the
    # votes relationships tells the ORM "the database will clean up the children",
    # so the database has to actually be told to. Without it, deleting a post or
    # user that has votes raises ForeignKeyViolation.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # index=True: the unique constraint's index starts with user_id, so lookups
    # and aggregates keyed on post_id need an index of their own.
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    value: Mapped[int] = mapped_column(Integer, nullable=False)          # +1 or -1

    # created_at: Mapped[int] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    # annotation was Mapped[int] on a DateTime column; harmless at runtime
    # (the explicit type wins) but wrong for type checkers and readers.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    user: Mapped[User] = relationship(back_populates="votes")
    post: Mapped[Post] = relationship(back_populates="votes")

    __table_args__ = (
        UniqueConstraint("user_id", "post_id", name="uq_votes_user_post"),
        CheckConstraint("value IN (-1, 1)", name="ck_votes_value"),
    )

# Declared after Vote so the subquery can reference it. This is evaluated as a
# correlated subquery inside the main SELECT, so it costs no extra round trip
# and never triggers a lazy load. coalesce is required: SUM over zero rows is
# NULL, which fails `score: int` validation.
Post.score = column_property(
        select(func.coalesce(func.sum(Vote.value), 0))
        .where(Vote.post_id == Post.id)
        .correlate_except(Vote)
        .scalar_subquery()
    )
'''
Post.score = column_property(
        select(func.coalesce(func.sum(Vote.value), 0))
        .where(Vote.post_id == Post.id)
        .correlate_except(Vote)
        .scalar_subquery()
    )

column_property(...) — "treat score like a normal column on Post, except its value comes from this piece of SQL instead of from a stored column." That's the key idea: to the rest of your code, post.score looks exactly like post.title. Nothing else in your app had to change.

func.sum(Vote.value) — SQL's SUM(). Add up the value column.

func.coalesce(..., 0) — "if the answer is empty, use 0 instead." Needed because SQL's SUM over zero rows returns NULL, not 0. A brand new post has no votes, so without coalesce you'd get None, and score: int in your Pydantic schema would reject it. COUNT doesn't have this quirk — only SUM — which is why your vote-stats endpoint doesn't need coalesce.

.where(Vote.post_id == Post.id) — only count votes belonging to this post. This is the line that connects the little query to the row it's attached to.

.correlate_except(Vote) — a technical instruction meaning: "in this inner query, only votes is yours; posts belongs to the outer query." Without it SQLAlchemy might add posts to the inner query too, and you'd get every post's votes mixed together instead of just this one's.

.scalar_subquery() — "this mini-query returns one single value, not a table of rows." Which lets it be used where a column would go.

What it actually produces

That whole block turns into this SQL, which I ran to confirm:

SELECT posts.id, posts.title, posts.content,osted,
       (SELECT coalesce(sum(votes.value), 0)
        FROM votes
        WHERE votes.post_id = posts.id)      ← this is score
FROM posts                                                                                                           
That inner (SELECT ...) in the middle is your column_property. The database runs it once per post row, internally,    and hands back the totals together with everng for Python to await.
                                                                                                                      Why it sits at the bottom of the file instea

Look at the order of your classes: Post is defined at line ~41, Vote at line ~83. The score query mentions Vote — but inside the body of class Post, Vote doesn't file top to bottom, so it would fail withNameError.

Putting Post.score = ... after both classes hemy is fine with attributes being attachedto a model after the class is written.

The one catch

Because score is computed during the SELECT, the value is a snapshot from the moment you loaded the post. If you then
insert a vote, the Python object still holdsidea the database changed underneath it.

I measured exactly this:

score before:              0
stale in memory:           0     ← after inserting a +1 vote and committing
after refresh(['score']):  1

That's the reason for these two lines you now have:

- in vote_post: await db.refresh(post, attribute_names=["score"]) — re-ask the database for the new total after the vote is saved. Without it the arrow lights up but the number doesn't move.
- in create_post and the update handlers: atore"] — a brand new post was INSERTed, neverSELECTed, so score was never computed at all. Asking for it would have triggered the very lazy load we were avoiding. That was the 4 test failures you

Short version: Post.score is a fake column.  table — it's a small SUM query bolted ontoevery SELECT of a post, so the database delivers the total alongside the title. That's why it's fast, why it works with async, and why it needs an explicit ref



***Look at what db.delete(post) actually sends:
With passive_deletes=True (what you have):
DELETE FROM posts WHERE posts.id = 1

Without it:
SELECT votes.id, votes.user_id, votes.post_id, ...   ← load the children
DELETE FROM votes WHERE votes.id = 1                 ← one DELETE per child
DELETE FROM posts WHERE posts.id = 1

The two cascades live in different worlds

cascade="all, delete-orphan" is a Python instruction. It tells SQLAlchemy: "when I delete a post, you go find its votes and delete them too." SQLAlchemy does the work — it queries for the children, then issues a DELETE for each one. That's the second output above.

ondelete="CASCADE" is a database instruction. It's written into the table definition itself, and tells Postgres: "if a post row disappears, wipe the vote rows pointing at it." Postgres does the work, silently, in the same statement.

Two different workers, same job.

So why do you need both?

Because you also wrote passive_deletes=True. That flag means:

▎ "SQLAlchemy, don't bother deleting the children. The database will handle it."

It switches off the Python side. That's exactly what the first output shows — just DELETE FROM posts, nothing about votes.

And if the database was never told to cascade, then nobody deletes the votes. The ORM stepped aside, the database doesn't know it's supposed to act, so Postgres just refuses the whole thing:

IntegrityError: update or delete on table "posts" violates foreign key
constraint "votes_post_id_fkey"
DETAIL: Key (id)=(1) is still referenced from table "votes"

That's the error I hit on your schema before we fixed the migration.

Here's the full picture:

┌─────────┬─────────────────┬──────────┬─────────────────────────────────────────────────────────────────┐
│ cascade │ passive_deletes │ ondelete │                             Result                              │
├─────────┼─────────────────┼──────────┼─────────────────────────────────────────────────────────────────┤
│ ✅      │ ❌              │ ❌       │ Works. Python deletes the children.                             │
├─────────┼─────────────────┼──────────┼─────────────────────────────────────────────────────────────────┤
│ ✅      │ ✅              │ ❌       │ Broken. Python stepped aside, DB wasn't told. ← you were here   │
├─────────┼─────────────────┼──────────┼─────────────────────────────────────────────────────────────────┤
│ ✅      │ ✅              │ ✅       │ Works. DB deletes the children in one statement. ← you are here │
└─────────┴─────────────────┴──────────┴─────────────────────────────────────────────────────────────────┘

So: it's not that cascade is insufficient on its own. It's that passive_deletes=True hands the job to the database, and you have to actually give the database the job.

Why bother with passive_deletes at all?

Speed, at scale. Deleting a user means deleting their posts, and every vote on every one of those posts. Without passive_deletes, SQLAlchemy loads all of it into Python memory first and fires one DELETE per row. A user with 500 posts averaging 50 votes each = 25,000 rows pulled into memory and 25,000 individual DELETE statements.

With passive_deletes=True + ondelete="CASCADE", it's a single DELETE FROM users and Postgres cleans up internally. Enormously faster.

And one reason to keep ondelete regardless

The Python cascade only fires when you go through the ORM. ondelete="CASCADE" is part of the table, so it protects you everywhere:

- populate_db.py or any raw SQL
- deleting a row by hand in psql or pgAdmin
- a future admin panel, a cleanup script, another service on the same database

The ORM rule is a habit your app follows. The FK rule is a law the database enforces. Belt and braces — and the reason I suggested both in the guide even before passive_deletes entered the picture.


'''