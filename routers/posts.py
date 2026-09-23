from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status,Query
from sqlalchemy import select,func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import models
from database import get_db
from schemas import PostCreate, PostResponse, PostUpdate, PaginatedPostsResponse,VoteResponse,VoteRequest
from auth import CurrentUser

router = APIRouter()


@router.get("", response_model=PaginatedPostsResponse)
async def get_posts(
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    ):

    count_result = await db.execute(select(func.count()).select_from(models.Post))
    total = count_result.scalar() or 0

    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .order_by(models.Post.date_posted.desc())
        .offset(skip)
        .limit(limit),
    )
    posts = result.scalars().all()

    has_more = skip+len(posts) < total
    return PaginatedPostsResponse(
        posts=[PostResponse.model_validate(post) for post in posts],
        total=total,
        skip=skip,
        limit=limit,
        has_more=has_more,
    )


@router.post(
    "",
    response_model=PostResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_post(post: PostCreate,
                    current_user: CurrentUser,
                    db: Annotated[AsyncSession, Depends(get_db)]
                ):


    new_post = models.Post(
        title=post.title,
        content=post.content,
        user_id=current_user.id,
    )
    db.add(new_post)
    await db.commit()
    # await db.refresh(new_post, attribute_names=["author"])
    # "score" must be refreshed too: a freshly INSERTed Post never went through
    # a SELECT, so the score column_property was never evaluated. Reading
    # post.score during response serialization would lazy-load -> MissingGreenlet.
    await db.refresh(new_post, attribute_names=["author", "score"])
    return new_post


@router.get("/{post_id}", response_model=PostResponse)
async def get_post(post_id: int, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(models.Post)
        .options(selectinload(models.Post.author))
        .where(models.Post.id == post_id),
    )
    post = result.scalars().first()
    if post:
        return post
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")


@router.put("/{post_id}", response_model=PostResponse)
async def update_post_full(
    post_id: int,
    post_data: PostCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.Post).where(models.Post.id == post_id))
    post = result.scalars().first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        )

    if post.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not Authorized to update this post",
        )
    post.title = post_data.title
    post.content = post_data.content


    await db.commit()
    # await db.refresh(post, attribute_names=["author"])
    await db.refresh(post, attribute_names=["author", "score"])
    return post


@router.patch("/{post_id}", response_model=PostResponse)
async def update_post_partial(
    post_id: int,
    post_data: PostUpdate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(models.Post).where(models.Post.id == post_id))
    post = result.scalars().first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        )
    if post.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not Authorized to update this post",
        )
    update_data = post_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(post, field, value)

    await db.commit()
    # await db.refresh(post, attribute_names=["author"])
    await db.refresh(post, attribute_names=["author", "score"])
    return post


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    post_id: int, 
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(models.Post).where(models.Post.id == post_id))
    post = result.scalars().first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        )
    if post.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not Autorize to delete this post",
        )
    await db.delete(post)
    await db.commit()

@router.post("/{post_id}/vote",response_model=VoteResponse)
async def vote_post(
    post_id: int,
    vote_req: VoteRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(models.Post).where(models.Post.id == post_id))
    post = result.scalars().first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        )
    if post.user_id == current_user.id :
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot vote on your own post",
        )
    result = await db.execute(
        select(models.Vote)
        .where(models.Vote.post_id == post_id , models.Vote.user_id == current_user.id))
    
    vote = result.scalars().first()

    # --- previous version, kept for reference ----------------------------
    # if not vote:
    #     new_vote = models.Vote(
    #             user_id=current_user.id,
    #             post_id=post_id,
    #             value=vote_req.value,
    #         )
    #     db.add(new_vote)
    #     await db.commit()
    #     #await db.refresh(new_vote, attribute_names=["user"])
    #     #await db.refresh(new_vote, attribute_names=["post"])
    #     my_vote = vote_req.value
    #     return VoteResponse(post_id=post_id, score=post.score, my_vote=my_vote)
    # else:
    #     if vote.value == vote_req.value:
    #         await db.delete(vote)
    #         await db.commit()
    #         my_vote = None
    #         return VoteResponse(post_id=post_id, score=post.score, my_vote=my_vote)
    #     else:
    #         vote.value = vote_req.value
    #         await db.commit()
    #         await db.refresh(vote, attribute_names=["score"])  # KeyError: Vote has no "score"
    #         await db.refresh(vote, attribute_names=["score"])  # duplicated
    #         my_vote = vote_req.value
    #         return vote                                        # ORM object, not VoteResponse
    #
    # Reshaped into one commit / one refresh / one return. A return inside each
    # of three branches is what let the last branch drift out of sync with the
    # other two, and none of them refreshed the stale score.
    # ---------------------------------------------------------------------

    if not vote:
        db.add(
            models.Vote(
                user_id=current_user.id,
                post_id=post_id,
                value=vote_req.value,
            ),
        )
        my_vote = vote_req.value
    elif vote.value == vote_req.value:
        # same arrow clicked twice -> toggle the vote off
        await db.delete(vote)
        my_vote = None
    else:
        # opposite arrow clicked -> switch direction
        vote.value = vote_req.value
        my_vote = vote_req.value

    try:
        await db.commit()
    except IntegrityError as err:
        # two concurrent requests both saw "no existing vote" and both inserted;
        # uq_votes_user_post caught the loser.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vote already recorded, please retry",
        ) from err

    # post.score was evaluated when the post was loaded, i.e. before this write,
    # so it is stale here. Without this refresh the arrow highlights but the
    # number does not move until the page is reloaded.
    await db.refresh(post, attribute_names=["score"])
    return VoteResponse(post_id=post_id, score=post.score, my_vote=my_vote)

