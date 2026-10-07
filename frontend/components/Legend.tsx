/* Shared color key for node states, used by both the Graph and Timeline
 * views. Swatch colors (.sw.*) are defined once in globals.css next to the
 * node/clip rules, so the two views can never drift apart. */

export function Legend() {
  return (
    <span className="legend">
      <span>
        <span className="sw normal" />
        normal
      </span>
      <span>
        <span className="sw slice" />
        in failure slice
      </span>
      <span>
        <span className="sw failure" />
        failure target
      </span>
      <span>
        <span className="sw terminal" />
        terminal
      </span>
      <span>
        <span className="sw selected" />
        selected
      </span>
    </span>
  );
}
