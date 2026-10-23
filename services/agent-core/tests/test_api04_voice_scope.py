"""API-04 on the voice socket (VOC-26, D86): the profile token travels as the `jana.profile.<token>` subprotocol and is
checked exactly like `X-Profile-Token`. Uses the ASGI socket harness of the M31 voice tests; no speech model, no TCP."""

import asyncio

from test_m31_voice_socket import Socket, setup, started


def api04_voice_socket_profile_scope(tmp_path):
    """Only `jana.voice.1` is echoed (never a token); another profile's session is a missing resource (4404); no or a
    wrong profile token is refused (4401); and the socket closes with 4401 the moment that profile token ends."""

    async def scenario():
        core, sessions, endpoints, _, runtime, app = setup(tmp_path)
        try:
            other = Socket(app, sessions[2])  # profile B's session, with profile A's token
            reply = await other.receive()
            assert reply["type"] == "websocket.close" and reply["code"] == 4404, reply
            await other.close()
            for profile in (None, "not-a-token"):
                refused = Socket(app, sessions[0], profile=profile)
                reply = await refused.receive()
                assert reply["type"] == "websocket.close" and reply["code"] == 4401
                await refused.close()
            assert not endpoints  # nothing reached the speech side

            socket = Socket(app, sessions[0])
            accepted = await socket.receive()
            assert accepted["type"] == "websocket.accept" and accepted.get("subprotocol") == "jana.voice.1"
            assert "profile-a-secret" not in str(accepted) and "launch-secret" not in str(accepted)
            await socket.close()

            live, endpoint = await started(app, sessions[0], endpoints)
            del core.directory.live["profile-a-secret"]  # the profile token ends (close, switch or inactivity)
            ended = await live.receive()
            assert ended["type"] == "websocket.close" and ended["code"] == 4401
            assert endpoint.closed
            await live.close()
        finally:
            await runtime.close()

    asyncio.run(scenario())
