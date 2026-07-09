<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Curator Orchestration</title>
</head>
<body>
  <main>
    <h1>Curator Orchestration</h1>

    <section id="what">
      <h2>What</h2>
      <p>
        Curator orchestration turns an accepted goal into a durable workflow session.
        The implemented path is writer provider, deterministic verifier, fresh-context
        reviewer provider, and human confirmation gate. Provider runs are ledgered with
        provider identity, context package id, events, responses, evidence, and scheduler
        decisions.
      </p>
    </section>

    <section id="how">
      <h2>How</h2>
      <pre><code>shell/repl.py
  - records discussion, approval, provider setup commands, resume input
app.py
  - creates accepted-goal workflow sessions
scheduler/engine.py
  - builds context packages
  - resolves provider drivers from slot bindings
  - pauses on missing provider, dirty workspace, provider handoff, or missing verification
providers/claude_code.py and providers/codex_cli.py
  - render context package requests into real CLI prompts
  - stream events and capture workspace evidence
harness/verifier.py
  - discovers project verification commands
  - records verification evidence
harness/workspace.py
  - requires clean git baseline for writer runs
  - records tracked diff and untracked files after provider execution</code></pre>
      <p>
        Provider setup accepts only <code>claude-code</code> and <code>codex</code>.
        Detection requires the CLI binary to exist and <code>--version</code> to exit
        successfully. Broken CLIs are not persisted as active provider profiles.
      </p>
    </section>

    <section id="why">
      <h2>Why</h2>
      <p>
        The orchestration boundary makes real provider behavior auditable. The scheduler
        never assumes success from a missing provider, empty verifier, or pre-existing
        dirty workspace. This gives users a basic reliable interaction standard: visible
        setup requirements, typed failures, deterministic verification, inspectable
        evidence, and explicit resume choices.
      </p>
    </section>

    <section id="future">
      <h2>Future improvements/considerations/trade-offs</h2>
      <ul>
        <li>Support provider-specific structured result parsing for verification commands.</li>
        <li>Add provider health scoring before automatic writer/reviewer selection.</li>
        <li>Introduce explicit development fixtures without exposing them as user providers.</li>
        <li>Offer a guarded dirty-workspace override with clear evidence partitioning.</li>
      </ul>
    </section>
  </main>
</body>
</html>
