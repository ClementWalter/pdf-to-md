// components/FinalReview.tsx — readyToMoveOn gating decision
//
// Decides if the project is complete. reasoning field feeds back to next pass.

import { Task, tables } from "../smithers.js";
import { FinalReviewSchema } from "../db/schemas.js";
import { makeFinalReviewer } from "../agents.js";
import FinalReviewPrompt from "../steps/final-review.mdx";

interface FinalReviewProps {
  nodeId: string;
  /** Current pass number */
  pass: number;
  /** Implement output */
  whatWasDone: string;
  believesComplete: boolean;
  /** Test results */
  testsPassed: boolean;
  testsPassCount: number;
  testsFailCount: number;
  /** Review results */
  reviewSeverity: string;
  reviewApproved: boolean;
}

export function FinalReview({
  nodeId,
  pass,
  whatWasDone,
  believesComplete,
  testsPassed,
  testsPassCount,
  testsFailCount,
  reviewSeverity,
  reviewApproved,
}: FinalReviewProps) {
  return (
    <Task
      id={nodeId}
      output={tables.final_review}
      outputSchema={FinalReviewSchema}
      agent={makeFinalReviewer()}
      retries={1}
    >
      <FinalReviewPrompt
        pass={String(pass)}
        whatWasDone={whatWasDone}
        believesComplete={String(believesComplete)}
        testsPassed={String(testsPassed)}
        testsPassCount={String(testsPassCount)}
        testsFailCount={String(testsFailCount)}
        reviewSeverity={reviewSeverity}
        reviewApproved={String(reviewApproved)}
      />
    </Task>
  );
}
