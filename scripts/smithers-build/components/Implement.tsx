// components/Implement.tsx — Execute implementation with feedback loop
//
// Implements the next atomic unit of work, incorporating feedback from previous passes

import { Task, tables } from "../smithers.js";
import { ImplementSchema } from "../db/schemas.js";
import { makeImplementer } from "../agents.js";
import ImplementPrompt from "../steps/implement.mdx";

interface ImplementProps {
  nodeId: string;
  /** Previous iteration's whatWasDone (for context continuity) */
  previousWork: string | undefined;
  /** Previous iteration's nextSmallestUnit */
  previousNextUnit: string | undefined;
  /** Review feedback from previous iteration */
  reviewFeedback: string | undefined;
  /** Failing tests from previous iteration */
  failingTests: string | undefined;
  /** Final review reasoning from previous iteration */
  finalReviewFeedback: string | undefined;
  /** Current pass number */
  pass: number;
}

export function Implement({
  nodeId,
  previousWork,
  previousNextUnit,
  reviewFeedback,
  failingTests,
  finalReviewFeedback,
  pass,
}: ImplementProps) {
  return (
    <Task
      id={nodeId}
      output={tables.implement}
      outputSchema={ImplementSchema}
      agent={makeImplementer()}
      retries={1}
    >
      <ImplementPrompt
        pass={String(pass)}
        previousWork={previousWork ?? ""}
        previousNextUnit={previousNextUnit ?? ""}
        reviewFeedback={reviewFeedback ?? ""}
        failingTests={failingTests ?? ""}
        finalReviewFeedback={finalReviewFeedback ?? ""}
      />
    </Task>
  );
}
