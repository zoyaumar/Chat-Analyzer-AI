"""`GET /users/{user_id}` and the account timestamp.

Attribution only needs a name, so a message's `user_id` can now be turned into
a username — without widening what any client can read about a user.
"""


async def _register(client, username: str) -> dict:
    response = await client.post(
        "/users/register", json={"username": username, "password": "pw123456"}
    )
    assert response.status_code == 200
    return response.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_registration_reports_created_at(client):
    """`users.created_at` is exposed, so a client can say when an account started."""
    body = await _register(client, "carol")

    assert body["username"] == "carol"
    assert body["created_at"]


async def test_any_signed_in_user_can_attribute_a_message_author(client, user_and_token):
    _, _, token = user_and_token
    bob_id = (await _register(client, "bob"))["id"]

    response = await client.get(f"/users/{bob_id}", headers=_auth(token))

    assert response.status_code == 200
    assert response.json()["username"] == "bob"


async def test_a_profile_never_leaks_the_password_hash(client, user_and_token):
    _, _, token = user_and_token
    me = (await client.get("/users/me", headers=_auth(token))).json()

    body = (await client.get(f"/users/{me['id']}", headers=_auth(token))).json()

    assert set(body) == {"id", "username", "created_at"}  # public shape: no hash, no email


async def test_an_unknown_user_is_404(client, user_and_token):
    _, _, token = user_and_token

    response = await client.get("/users/424242", headers=_auth(token))

    assert response.status_code == 404


async def test_the_lookup_requires_a_token(client, user_and_token):
    _, _, token = user_and_token
    me = (await client.get("/users/me", headers=_auth(token))).json()

    assert (await client.get(f"/users/{me['id']}")).status_code == 401


async def test_users_me_is_not_captured_by_the_id_route(client, user_and_token):
    """`/users/me` is registered before `/users/{user_id}`, so it still wins."""
    username, _, token = user_and_token

    body = (await client.get("/users/me", headers=_auth(token))).json()

    assert body["username"] == username


async def test_a_non_numeric_id_is_422(client, user_and_token):
    _, _, token = user_and_token

    assert (await client.get("/users/not-an-id", headers=_auth(token))).status_code == 422