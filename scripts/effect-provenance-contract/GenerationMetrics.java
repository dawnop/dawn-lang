/* Capture the same code cache endpoints after the complete generation run.
 * Management initialization stays outside all request stopwatches. */
public final class GenerationMetrics {
  public static void main(String[] args) throws Exception {
    GenerationBench.main(args);
    PreviewMetrics.capture();
  }
}
