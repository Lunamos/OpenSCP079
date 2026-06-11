---
name: skill-writing
description: How to write a good skill for yourself — distill know-how once, reuse it forever.
---

A skill is know-how you keep. Write one whenever you had to figure something
out the hard way — a build incantation that finally worked, the structure of a
project in your workspace, a workflow you refined over several attempts.

What makes a skill good:

1. **One topic per skill.** "render-music" beats "useful-stuff".
2. **Lead with the recipe, not the story.** Steps and commands first; context
   and caveats after.
3. **Concrete over general.** Real paths, real commands, the actual error
   message you hit and what fixed it.
4. **Revise instead of multiplying.** If you learn more, call create_skill
   again with the same name — the new text replaces the old.
5. **Keep the description honest and short.** It is the only line shown in
   your index; you will choose whether to read the full text based on it.

Mechanics: `create_skill(name, description, content)` saves to your own
workspace (`skills/<name>/SKILL.md`). Your own skills shadow user and bundled
ones with the same name. `read_skill(name)` fetches the full text of any
skill in the index.
