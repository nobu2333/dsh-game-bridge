"""EntityMemory：外观聚类 / 行为角色 / 伤害归因。"""

import numpy as np

from dsh_game_core.entity_memory import EntityMemory, appearance_signature
from dsh_game_core.tracking import Track


def make_track(track_id=1, x=0.6, y=0.5, vx=-0.2, vy=0.0, kind="threat"):
    return Track(id=track_id, kind=kind, x=x, y=y, vx=vx, vy=vy, age=1, last_t=0.0)


def color_frame(rgb=(220, 40, 40), shape=(120, 200, 3)):
    frame = np.zeros(shape, dtype=np.uint8)
    frame[:, :] = (rgb[2], rgb[1], rgb[0])  # BGR
    return frame


def test_appearance_signature_and_cluster():
    frame = color_frame((220, 40, 40))
    track = make_track(x=0.5, y=0.5)
    signature = appearance_signature(frame, track)
    assert signature is not None
    assert abs(float(signature.sum()) - 1.0) < 1e-5
    memory = EntityMemory()
    first = memory.update([track], frame, (0.4, 0.5), hp=3, now=0.0)
    second = memory.update([make_track(track_id=2, x=0.6, y=0.5)], frame, (0.4, 0.5), hp=3, now=0.1)
    assert first[0]["cluster"] == second[0]["cluster"]
    other = memory.update([make_track(track_id=3, x=0.6, y=0.5)], color_frame((40, 220, 40)), (0.4, 0.5), hp=3, now=0.2)
    assert other[0]["cluster"] != first[0]["cluster"]


def test_approaching_becomes_chaser():
    memory = EntityMemory()
    track = make_track(x=0.65, y=0.5, vx=-0.3)
    roles = []
    for index in range(12):
        result = memory.update([track], None, (0.4, 0.5), hp=3, now=index * 0.05)
        roles.append(result[0]["role"])
    assert "approaching" in roles
    assert roles[-1] == "chaser"


def test_hp_drop_marks_cluster_harmful():
    memory = EntityMemory()
    frame = color_frame((220, 40, 40))
    track = make_track(x=0.42, y=0.5, vx=-0.1)
    memory.update([track], frame, (0.4, 0.5), hp=3, now=0.0)
    result = memory.update([track], frame, (0.4, 0.5), hp=2, now=0.05)
    assert result
    assert result[0]["harmful_hits"] >= 1
    assert memory.clusters()[0]["harmful_hits"] >= 1


def test_memory_tolerates_garbage():
    memory = EntityMemory()
    assert memory.update(None, None, (0.5, 0.5)) == []
    assert memory.update([None, object()], None, (0.5, 0.5)) == []
    assert memory.role_counts()["tracks"] == 0
