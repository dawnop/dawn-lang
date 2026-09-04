cuda_tile.module @m {
  entry @cce_mean(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = reshape %1 : tile<i32> -> tile<1xi32>
    %3 = broadcast %2 : tile<1xi32> -> tile<64xi32>
    %4 = iota : tile<64xi32>
    %5 = addi %3, %4 : tile<64xi32>
    %6 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %7 = broadcast %6 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %8 = offset %7, %5 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %9, %10 = load_ptr_tko weak %8 token=%0 : tile<64xptr<f64>> -> tile<64xf64>, token
    %11 = reduce %9 dim=0 identities=[0.0 : f64] : tile<64xf64> -> tile<f64> (%12: tile<f64>, %13: tile<f64>) {
      %14 = addf %12, %13 rounding<nearest_even> : tile<f64>
      yield %14 : tile<f64>
    }
    %15 = reshape %11 : tile<f64> -> tile<1xf64>
    %16 = broadcast %15 : tile<1xf64> -> tile<1xf64>
    %17 = constant <i32: 0> : tile<i32>
    %18 = constant <f64: 64.0> : tile<1xf64>
    %19 = divf %16, %18 rounding<nearest_even> : tile<1xf64>
    %20 = reshape %17 : tile<i32> -> tile<1xi32>
    %21 = broadcast %20 : tile<1xi32> -> tile<1xi32>
    %22 = iota : tile<1xi32>
    %23 = addi %21, %22 : tile<1xi32>
    %24 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %25 = broadcast %24 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %26 = offset %25, %23 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %27 = store_ptr_tko weak %26, %19 token=%10 : tile<1xptr<f64>>, tile<1xf64> -> token
    return
  }
}
