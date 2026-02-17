// components/Test.tsx — Run pytest and report results
//
// Executes the test suite and reports pass/fail status with details

import { Task, tables } from "../smithers.js";
import { TestSchema } from "../db/schemas.js";
import { makeImplementer } from "../agents.js";
import TestPrompt from "../steps/test.mdx";

interface TestProps {
  nodeId: string;
  /** Files created by Implement step */
  filesCreated: string[];
  /** Files modified by Implement step */
  filesModified: string[];
  /** What was done in implementation */
  whatWasDone: string;
}

export function Test({
  nodeId,
  filesCreated,
  filesModified,
  whatWasDone,
}: TestProps) {
  return (
    <Task
      id={nodeId}
      output={tables.test_results}
      outputSchema={TestSchema}
      agent={makeImplementer()} // needs write access to fix import/dep errors
      retries={2}
    >
      <TestPrompt
        filesCreated={filesCreated.join("\n- ")}
        filesModified={filesModified.join("\n- ")}
        whatWasDone={whatWasDone}
      />
    </Task>
  );
}
