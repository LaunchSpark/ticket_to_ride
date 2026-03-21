from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


class ViewerPlaybackTests(unittest.TestCase):
    def test_move_playback_cursor_can_step_past_turn_thirty(self) -> None:
        playback_module = Path("apps/viewer/components/model/playback.jsx").read_text(encoding="utf-8")
        script = f"""{playback_module}

const matchData = {{
  rounds: [
    {{
      turns: Array.from({{ length: 35 }}, (_, index) => ({{ index }})),
    }},
  ],
}};

console.log(JSON.stringify(movePlaybackCursor(matchData, 0, 29, 1)));
"""
        result = subprocess.run(
            ["node", "--input-type=module"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(
            json.loads(result.stdout.strip()),
            {"roundIndex": 0, "turnIndex": 30, "changed": True},
        )


if __name__ == "__main__":
    unittest.main()
