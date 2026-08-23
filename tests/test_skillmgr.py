from dual_tmux.opsdir import prepare
from dual_tmux import skillmgr
from dual_tmux.store import save, tunnels_dir
from dual_tmux.config import AppConfig, write_config


def test_catalog_seed_and_trigger_subset(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    write_config(AppConfig(client="tm_box", server="tom7r", user="andy"))
    rows = skillmgr.list_catalog()
    names = {r["name"] for r in rows}
    assert "dual-tmux" in names
    assert "tmux-trigger" in names
    trig = skillmgr.enabled("trigger")
    assert trig[:2] == ["dual-tmux", "tmux-trigger"] or set(trig) >= {"dual-tmux", "tmux-trigger"}


def test_import_enable_teach_and_usage_log(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    write_config(AppConfig(client="tm_box", server="tom7r", user="andy"))
    extra = tmp_path / "extra" / "demo-skill"
    extra.mkdir(parents=True)
    (extra / "SKILL.md").write_text("---\nname: demo-skill\ndescription: demo\n---\n# demo\n")
    assert skillmgr.import_skill(str(extra)) == "demo-skill"
    skillmgr.set_enabled("demo-skill", "bullet", True)
    cfg = skillmgr.load_config()
    assert "demo-skill" in cfg["bullet"]
    save(tunnels_dir() / "dt-msg.json", {"name": "dt-msg", "op": "op_msg", "run": "run_msg"})
    msg = skillmgr.teach("dt-msg", ["demo-skill"])
    assert "demo-skill" in msg
    skillmgr.log_use("dt-msg", "demo-skill", True, "ok run")
    skillmgr.log_use("dt-msg", "demo-skill", False, "pane down")
    rows = skillmgr.read_log(limit=10, name="dt-msg")
    assert len(rows) >= 2
    assert rows[-1]["ok"] is False
    assert rows[-1]["skill"] == "demo-skill"
    fails = skillmgr.read_log(ok="no")
    assert all(not r["ok"] for r in fails)


def test_prepare_uses_trigger_subset(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    write_config(AppConfig(client="tm_box", server="tom7r", user="andy"))
    dest = prepare(
        {
            "name": "dt-msg",
            "op": "op_msg",
            "run": "run_msg",
            "runtime": {},
            "trigger": {},
            "bullet": {},
        }
    )
    assert (dest / ".opencode" / "skills" / "dual-tmux" / "SKILL.md").is_file()
    oc = (dest / "opencode.json").read_text()
    assert "dual-tmux" in oc
    assert "dt skill used" in (dest / "AGENTS.md").read_text()


def test_import_md_and_zip(tmp_path, monkeypatch):
    import zipfile

    monkeypatch.setenv("DUAL_TMUX_HOME", str(tmp_path))
    write_config(AppConfig(client="tm_box", server="tom7r", user="andy"))
    md = tmp_path / "solo.md"
    md.write_text("---\nname: solo-md\ndescription: from markdown\n---\n# hi\n")
    preview = skillmgr.preview_source(str(md))
    assert preview["kind"] == "md"
    assert preview["name"] == "solo-md"
    assert skillmgr.import_skill(str(md)) == "solo-md"
    zdir = tmp_path / "pack"
    zdir.mkdir()
    (zdir / "SKILL.md").write_text("---\nname: zip-skill\ndescription: from zip\n---\n# z\n")
    zpath = tmp_path / "pack.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(zdir / "SKILL.md", "SKILL.md")
    assert skillmgr.preview_source(str(zpath))["name"] == "zip-skill"
    assert skillmgr.import_skill(str(zpath)) == "zip-skill"
    names = {r["name"] for r in skillmgr.list_catalog()}
    assert "solo-md" in names and "zip-skill" in names
