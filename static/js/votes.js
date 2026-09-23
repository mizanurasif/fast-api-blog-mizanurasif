import { getToken } from '/static/js/auth.js';
import { getErrorMessage, showModal } from '/static/js/utils.js';

// Markup for one vote widget. Must stay structurally identical to the Jinja
// version in home.html / user_posts.html / post.html, or hydration silently
// misses posts appended by "Load More".
export function voteMarkup(post) {
  return `
    <div class="vote-box d-flex flex-column align-items-center flex-shrink-0" data-post-id="${post.id}">
      <button type="button" class="vote-btn vote-up" aria-label="Upvote" aria-pressed="false">&#9650;</button>
      <span class="vote-score fw-bold">${post.score}</span>
      <button type="button" class="vote-btn vote-down" aria-label="Downvote" aria-pressed="false">&#9660;</button>
    </div>
  `;
}

// Paint one box from a server response.
function paint(box, score, myVote) {
  box.querySelector('.vote-score').textContent = score;

  const up = box.querySelector('.vote-up');
  const down = box.querySelector('.vote-down');

  up.classList.toggle('voted-up', myVote === 1);
  down.classList.toggle('voted-down', myVote === -1);
  up.setAttribute('aria-pressed', myVote === 1 ? 'true' : 'false');
  down.setAttribute('aria-pressed', myVote === -1 ? 'true' : 'false');
}

// Counts are server-rendered and public; which arrow is highlight
// per-viewer, so it has to be fetched after load. Anonymous visitors skip this
// entirely and just see the numbers.
// Pass specific boxes after appending new posts; omit for the whole page.
export async function hydrateMyVotes(boxes = null) {
  const token = getToken();
  if (!token) return;

  const targets = boxes || [...document.querySelectorAll('.vote-box')];
  if (targets.length === 0) return;

  const params = new URLSearchParams();
  for (const box of targets) {
    params.append('post_ids', box.dataset.postId);
  }

  try {
    const response = await fetch(`/api/users/me/votes?${params}`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    // Stale token or similar: leave the arrows neutral rather than guessing.
    if (!response.ok) return;

    const myVotes = await response.json();
    for (const box of targets) {
      const myVote = myVotes[box.dataset.postId]; // JSON object k
      if (myVote) {
        paint(box, box.querySelector('.vote-score').textContent, myVote);
      }
    }
  } catch (error) {
    console.error('Error loading your votes:', error);
  }
}

// One delegated listener. Survives posts appended later by "Load
export function initVoting(container = document) {
  container.addEventListener('click', async (event) => {
    const btn = event.target.closest('.vote-btn');
    if (!btn) return;

    const box = btn.closest('.vote-box');
    const postId = box.dataset.postId;
    const value = btn.classList.contains('vote-up') ? 1 : -1;

    const token = getToken();
    if (!token) {
      // Anonymous visitor: send them to log in and come back to t
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.href = `/login?next=${next}`;
      return;
    }

    // Disable both arrows so a double-click can't fire two toggle
    const buttons = box.querySelectorAll('.vote-btn');
    buttons.forEach((b) => { b.disabled = true; });

    try {
      const response = await fetch(`/api/posts/${postId}/vote`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ value }),
      });

      if (response.status === 401) {
        const next = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.href = `/login?next=${next}`;
        return;
      }

      if (response.ok) {
        // Trust the server's numbers. No optimistic local arithmetic, or the
        // display drifts from the database after any error.
        const data = await response.json();
        paint(box, data.score, data.my_vote);
        return;
      }

      // 403 own post, 409 vote race, 404 deleted post.
      const error = await response.json();
      document.getElementById('errorMessage').textContent = getErrorMessage(error);
      showModal('errorModal');
    } catch (error) {
      document.getElementById('errorMessage').textContent =
        'Network error. Please check your connection and try again.';
      showModal('errorModal');
    } finally {
      buttons.forEach((b) => { b.disabled = false; });
    }
  });
}