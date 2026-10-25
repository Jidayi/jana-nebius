"""The imported visual features across real APIs, stored history and restarts; all input is synthetic."""
import asyncio

from api_harness import start_core, stop_core
from test_m10a_profiles import Api, student
from test_m33a_history import _ended
from visual_feature_fixture import seed_visuals


def test_visuals_survive_reload_history_and_restart(tmp_path):
    async def run():
        r = await start_core(tmp_path, stage="S3")
        r.core.planner = r.runtime.planner
        api = Api(r)
        profile = await api.add(student("Synthetic visual QA", "18_plus"))
        token = await api.token(profile)
        session = await _ended(api, r, token)
        ids = await seed_visuals(r.core, session)
        snapshot = (await api.call("GET", f"/v1/sessions/{session}/snapshot", profile=token)).json()
        assert snapshot["boards"][ids["board"]]["annotation"]["mark"] == "circle"
        assert snapshot["parts"][ids["sketch_part"]]["sketch"]["sketch_id"] == ids["sketch"]
        history = (await api.call("GET", f"/v1/history/{session}", profile=token)).json()
        assert history["parts"][ids["part"]]["boards"][0]["annotation"]["mark"] == "circle"
        start = await api.call("POST", f"/v1/visuals/{ids['visuals']['number-line']}/practice",
                               {"part_id": "sol.from"}, profile=token)
        assert start.status_code == 200, start.text
        step = start.json()["step_id"]
        assert r.core.records.failures == 0
        await stop_core(r)

        r = await start_core(tmp_path, stage="S3")
        r.core.planner = r.runtime.planner
        api = Api(r)
        token = await api.token(profile)
        try:
            snapshot = (await api.call("GET", f"/v1/sessions/{session}/snapshot", profile=token)).json()
            assert snapshot["boards"][ids["board"]]["manipulation"]["step_id"] == step
            replay = await api.call("GET", f"/v1/boards/{ids['board']}/replay", profile=token)
            assert replay.status_code == 200, replay.text
            assert any(i["event"]["type"] == "board.annotate" for i in replay.json()["items"])
            answer = await api.call("POST", f"/v1/visuals/{ids['visuals']['number-line']}/answer",
                                    {"client_answer_id": "cli_01JZ0000000000000000000001", "step_id": step,
                                     "values": [{"part_id": "sol.from", "value": "4"}]}, profile=token)
            assert answer.status_code == 200, answer.text
            assert answer.json()["status"] == "correct", answer.text
            assert answer.json()["check_id"]
            for diagram, part, wrong, correct in [
                ("function-graph", "f.root1", "(9, 0)", "(1, 0)"),
                ("free-body", "W", "49 N at 90", "49 N at 270"),
            ]:
                visual_id = ids["visuals"][diagram]
                for value, expected in [(wrong, "incorrect"), (correct, "correct")]:
                    started = await api.call("POST", f"/v1/visuals/{visual_id}/practice",
                                             {"part_id": part}, profile=token)
                    assert started.status_code == 200, started.text
                    submitted = await api.call("POST", f"/v1/visuals/{visual_id}/answer",
                                               {"client_answer_id": "cli_01JZ0000000000000000000001",
                                                "step_id": started.json()["step_id"],
                                                "values": [{"part_id": part, "value": value}]}, profile=token)
                    assert submitted.status_code == 200, submitted.text
                    assert submitted.json()["status"] == expected, submitted.text
                    assert submitted.json()["check_id"]
            removed = await api.call("DELETE", f"/v1/sketches/{ids['sketch']}", profile=token)
            assert removed.status_code == 204, removed.text
            history = (await api.call("GET", f"/v1/history/{session}", profile=token)).json()
            assert ids["sketch_part"] not in history["parts"]
            assert "manipulation" not in r.core.sessions[session].state["boards"][ids["board"]]
            assert r.core.records.failures == 0
            other = await api.add(student("Other synthetic QA", "18_plus"))
            other_token = await api.token(other)
            assert (await api.call("GET", f"/v1/history/{session}", profile=other_token)).status_code == 404
            assert (await api.call("POST", f"/v1/visuals/{ids['visuals']['free-body']}/practice",
                                   {"part_id": "W"}, profile=other_token)).status_code == 404
        finally:
            await stop_core(r)

    asyncio.run(run())
