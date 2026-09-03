cuda_tile.module @m {
  entry @prefix_sum(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = reshape %1 : tile<i32> -> tile<1xi32>
    %3 = broadcast %2 : tile<1xi32> -> tile<128xi32>
    %4 = iota : tile<128xi32>
    %5 = addi %3, %4 : tile<128xi32>
    %6 = constant <i32: 100> : tile<128xi32>
    %7 = cmpi less_than %5, %6, signed : tile<128xi32> -> tile<128xi1>
    %8 = constant <f64: 0.0> : tile<128xf64>
    %9 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %10 = broadcast %9 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %11 = offset %10, %5 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %12, %13 = load_ptr_tko weak %11, %7, %8 token=%0 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %14 = scan %12 dim=0 reverse=false identities=[0.0 : f64] : tile<128xf64> -> tile<128xf64> (%15: tile<f64>, %16: tile<f64>) {
      %17 = addf %15, %16 rounding<nearest_even> : tile<f64>
      yield %17 : tile<f64>
    }
    %18 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %19 = broadcast %18 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %20 = offset %19, %5 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %21 = store_ptr_tko weak %20, %14, %7 token=%13 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    return
  }
}
