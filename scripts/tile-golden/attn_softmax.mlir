cuda_tile.module @m {
  entry @attn_softmax(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 64> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<64xi32>
    %8 = iota : tile<64xi32>
    %9 = addi %7, %8 : tile<64xi32>
    %10 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %11 = broadcast %10 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %12 = offset %11, %9 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<64xptr<f64>> -> tile<64xf64>, token
    %15 = reduce %13 dim=0 identities=[-Infinity : f64] : tile<64xf64> -> tile<f64> (%16: tile<f64>, %17: tile<f64>) {
      %18 = maxf %16, %17 : tile<f64>
      yield %18 : tile<f64>
    }
    %19 = reshape %15 : tile<f64> -> tile<1xf64>
    %20 = broadcast %19 : tile<1xf64> -> tile<64xf64>
    %21 = subf %13, %20 rounding<nearest_even> : tile<64xf64>
    %22 = exp %21 : tile<64xf64>
    %23 = reduce %22 dim=0 identities=[0.0 : f64] : tile<64xf64> -> tile<f64> (%24: tile<f64>, %25: tile<f64>) {
      %26 = addf %24, %25 rounding<nearest_even> : tile<f64>
      yield %26 : tile<f64>
    }
    %27 = reshape %23 : tile<f64> -> tile<1xf64>
    %28 = broadcast %27 : tile<1xf64> -> tile<64xf64>
    %29 = divf %22, %28 rounding<nearest_even> : tile<64xf64>
    %30 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %31 = broadcast %30 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %32 = offset %31, %9 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %33 = store_ptr_tko weak %32, %29 token=%14 : tile<64xptr<f64>>, tile<64xf64> -> token
    return
  }
}
