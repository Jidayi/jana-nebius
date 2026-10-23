"""Explicit encrypted archive selection, a real HTTP round trip, and cleanup after a late import failure."""

from agent_core.engine.study import StudyDesk
from agent_core.store import study_archive
from test_m10a_profiles import student
from test_m10d_deletion_export import PASSPHRASE, _export, _with_exports


def test_study_archive_http_roundtrip_and_failed_import_removes_partial_profile(tmp_path, monkeypatch):
    async def scenario(api, runtime):
        profile = await api.add(student("Ama"))
        token = (await api.unlock(profile)).json()["profile_token"]
        directory = runtime.runtime.directory
        with directory.open_learner(profile) as conn:
            d = StudyDesk(conn, runtime.core.clock_ms, runtime.core.settings)
            source = d.create({"kind": "text", "title": "Biology", "text": "Enzymes are biological catalysts."})
            d.patch(source["source_id"], {"private": True})
        response, archive = await _export(
            api,
            token,
            tmp_path / "archive",
            kind="profile_archive",
            profile_ids=[profile],
            passphrase=PASSPHRASE,
            include_study_sources=True,
        )
        assert response.status_code == 202
        before = len(directory.summaries()["profiles"])
        original = study_archive.restore

        def fail_after_write(conn, folder, rows, blobs, deleted):
            original(conn, folder, rows, blobs, deleted)
            (folder / "late-import-canary").write_text("synthetic incomplete import")
            raise OSError("synthetic disk failure after content writes")

        monkeypatch.setattr(study_archive, "restore", fail_after_write)
        request = {"source": {"kind": "file", "path": str(archive)}, "passphrase": PASSPHRASE}
        failed = await api.call("POST", "/v1/profiles/import", request)
        assert failed.status_code >= 400
        assert len(directory.summaries()["profiles"]) == before
        assert not list(directory.data_dir.rglob("late-import-canary"))
        monkeypatch.setattr(study_archive, "restore", original)
        imported = await api.call("POST", "/v1/profiles/import", request)
        assert imported.status_code == 202, imported.text
        job = (await api.call("GET", "/v1/jobs/" + imported.json()["job_id"])).json()
        restored_id = job["result_ref"]
        with directory.open_learner(restored_id) as conn:
            d = StudyDesk(conn, runtime.core.clock_ms, runtime.core.settings)
            assert d.source(source["source_id"])["private"]
            assert d.chunks(source["source_id"], 1)["items"][0]["text"] == "Enzymes are biological catalysts."
            assert conn.execute("SELECT count(*) FROM study_jobs").fetchone()[0] == 0

    _with_exports(tmp_path, scenario)
