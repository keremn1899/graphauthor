/**
 * Exploration route for the settled Graph workspace.
 *
 * The implementation now belongs to the product. Keeping this small wrapper
 * lets visual experiments still open it without making production import a
 * lab component.
 */
import { GraphWorkspace } from "../../product/GraphWorkspace";

export function GraphMapLabPage() {
  return <GraphWorkspace />;
}
