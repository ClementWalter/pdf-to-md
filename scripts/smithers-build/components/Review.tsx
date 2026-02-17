// components/Review.tsx — Code quality and PRD compliance review
//
// Checks code quality, PRD compliance, test coverage, and Python best practices

import { Task, tables } from "../smithers.js";
import { ReviewSchema } from "../db/schemas.js";
import { makeReviewer } from "../agents.js";
import ReviewPrompt from "../steps/review.mdx";

interface ReviewProps {
  nodeId: string;
  /** Files created by Implement step */
  filesCreated: string[];
  /** Files modified by Implement step */
  filesModified: string[];
  /** What was done in implementation */
  whatWasDone: string;
  /** Test results */
  testsPassed: boolean;
  testsPassCount: number;
  testsFailCount: number;
  failingSummary: string | null;
}

export function Review({
  nodeId,
  filesCreated,
  filesModified,
  whatWasDone,
  testsPassed,
  testsPassCount,
  testsFailCount,
  failingSummary,
}: ReviewProps) {
  return (
    <Task
      id={nodeId}
      output={tables.review}
      outputSchema={ReviewSchema}
      agent={makeReviewer()}
      continueOnFail
      retries={1}
    >
      <ReviewPrompt
        filesCreated={filesCreated.join("\n- ")}
        filesModified={filesModified.join("\n- ")}
        whatWasDone={whatWasDone}
        testsPassed={String(testsPassed)}
        testsPassCount={String(testsPassCount)}
        testsFailCount={String(testsFailCount)}
        failingSummary={failingSummary ?? "none"}
      />
    </Task>
  );
}
