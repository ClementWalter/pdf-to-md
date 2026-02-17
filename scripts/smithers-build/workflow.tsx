// workflow.tsx — Root workflow composition for pdf2md
//
// Single Ralph loop: implement → test → review → final-review
// Each iteration implements one atomic unit and validates it.
// FinalReview gates whether to loop again or stop.

import { Workflow, Ralph, Sequence, Task, tables, smithers, useCtx } from "./smithers.js";
import { MAX_PASSES } from "./config.js";
import { PassTrackerSchema } from "./db/schemas.js";
import { Implement } from "./components/Implement.js";
import { Test } from "./components/Test.js";
import { Review } from "./components/Review.js";
import { FinalReview } from "./components/FinalReview.js";

export default smithers((ctx) => {
  // ─────────────────────────────────────────────────────────
  // Read previous outputs for data threading
  // ─────────────────────────────────────────────────────────

  const prevImplement = ctx.outputMaybe("implement", { nodeId: "implement" });
  const prevTest = ctx.outputMaybe("test_results", { nodeId: "test" });
  const prevReview = ctx.outputMaybe("review", { nodeId: "review" });
  const prevFinalReview = ctx.outputMaybe("final_review", { nodeId: "final-review" });
  const passTracker = ctx.outputMaybe("pass_tracker", { nodeId: "pass-tracker" });

  // ─────────────────────────────────────────────────────────
  // Pass tracking
  // ─────────────────────────────────────────────────────────

  const currentPass = passTracker?.totalIterations ?? 0;

  // ─────────────────────────────────────────────────────────
  // Termination conditions
  // ─────────────────────────────────────────────────────────

  const projectComplete = prevFinalReview?.readyToMoveOn ?? false;
  const done = currentPass >= MAX_PASSES || projectComplete;

  // ─────────────────────────────────────────────────────────
  // Data threading: feed previous outputs into next iteration
  // ─────────────────────────────────────────────────────────

  // Only feed failing tests back if tests actually failed
  const failingTests =
    prevTest && !prevTest.testsPassed ? (prevTest.failingSummary ?? undefined) : undefined;

  // ─────────────────────────────────────────────────────────
  // Workflow tree
  // ─────────────────────────────────────────────────────────

  return (
    <Workflow name="pdf2md-build">
      <Ralph
        until={done}
        maxIterations={MAX_PASSES * 20}
        onMaxReached="return-last"
      >
        <Sequence>
          {/* 1. Implement next atomic unit */}
          <Implement
            nodeId="implement"
            previousWork={prevImplement?.whatWasDone}
            previousNextUnit={prevImplement?.nextSmallestUnit ?? undefined}
            reviewFeedback={prevReview?.feedback}
            failingTests={failingTests}
            finalReviewFeedback={prevFinalReview?.reasoning}
            pass={currentPass + 1}
          />

          {/* 2. Run test suite */}
          <Test
            nodeId="test"
            filesCreated={prevImplement?.filesCreated ?? []}
            filesModified={prevImplement?.filesModified ?? []}
            whatWasDone={prevImplement?.whatWasDone ?? "initial implementation"}
          />

          {/* 3. Code review */}
          <Review
            nodeId="review"
            filesCreated={prevImplement?.filesCreated ?? []}
            filesModified={prevImplement?.filesModified ?? []}
            whatWasDone={prevImplement?.whatWasDone ?? "initial implementation"}
            testsPassed={prevTest?.testsPassed ?? false}
            testsPassCount={prevTest?.testsPassCount ?? 0}
            testsFailCount={prevTest?.testsFailCount ?? 0}
            failingSummary={prevTest?.failingSummary ?? null}
          />

          {/* 4. Final review — gating decision */}
          <FinalReview
            nodeId="final-review"
            pass={currentPass + 1}
            whatWasDone={prevImplement?.whatWasDone ?? "initial implementation"}
            believesComplete={prevImplement?.believesComplete ?? false}
            testsPassed={prevTest?.testsPassed ?? false}
            testsPassCount={prevTest?.testsPassCount ?? 0}
            testsFailCount={prevTest?.testsFailCount ?? 0}
            reviewSeverity={prevReview?.severity ?? "none"}
            reviewApproved={prevReview?.approved ?? false}
          />

          {/* 5. Pass tracker */}
          <Task
            id="pass-tracker"
            output={tables.pass_tracker}
            outputSchema={PassTrackerSchema}
          >
            {{
              totalIterations: currentPass + 1,
              summary: `Pass ${currentPass + 1} of ${MAX_PASSES} complete. ` +
                `Tests: ${prevTest?.testsPassed ? "PASS" : "FAIL"} ` +
                `(${prevTest?.testsPassCount ?? 0}/${(prevTest?.testsPassCount ?? 0) + (prevTest?.testsFailCount ?? 0)}). ` +
                `Review: ${prevReview?.severity ?? "pending"}. ` +
                `Final: ${prevFinalReview?.readyToMoveOn ? "READY" : "NOT READY"}.`,
            }}
          </Task>
        </Sequence>
      </Ralph>
    </Workflow>
  );
});
