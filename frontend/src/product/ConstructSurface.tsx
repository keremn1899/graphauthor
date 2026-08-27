import { GraphWorkspace } from "./GraphWorkspace";
import { ProductShell } from "./ProductShell";

/**
 * Constructions: the graph surface, over the graphs nobody has published.
 *
 * This replaced a runs workspace and, before that, a five-step wizard. Both
 * rested on the premise that the product runs construction. It does not: a
 * construction is an agent writing and running a program in its own session,
 * and the server owns neither the program nor the terminal it runs in. What
 * the product owns is the graph that comes out, and the decision about
 * whether it is any good.
 *
 * So this is not a second kind of screen. It is the same map reading a
 * different shelf, muted so a provisional graph cannot be mistaken for a
 * published one, carrying the one act a person has to perform: saying that a
 * construction is ready.
 *
 * Nothing here reads source text and nothing here runs. Both live in the
 * agent session, which is where the material and the program already are.
 *
 * The retired wizard, job runner, and workspace-v1 clients are intentionally
 * absent. Construction happens in an agent-authored workbook program; this
 * surface only presents its materialized graph.
 */
export function ConstructSurface() {
  return (
    <ProductShell active="construct">
      <GraphWorkspace productMode constructionMode />
    </ProductShell>
  );
}
