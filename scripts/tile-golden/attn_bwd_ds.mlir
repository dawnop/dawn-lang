cuda_tile.module @m {
  entry @attn_bwd_ds(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 64> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<64xi32>
    %8 = iota : tile<64xi32>
    %9 = addi %7, %8 : tile<64xi32>
    %10 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %11 = broadcast %10 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %12 = offset %11, %9 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<64xptr<f64>> -> tile<64xf64>, token
    %15 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %16 = broadcast %15 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %17 = offset %16, %9 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %18, %19 = load_ptr_tko weak %17 token=%14 : tile<64xptr<f64>> -> tile<64xf64>, token
    %20 = mulf %18, %13 rounding<nearest_even> : tile<64xf64>
    %21 = reduce %20 dim=0 identities=[0.0 : f64] : tile<64xf64> -> tile<f64> (%22: tile<f64>, %23: tile<f64>) {
      %24 = addf %22, %23 rounding<nearest_even> : tile<f64>
      yield %24 : tile<f64>
    }
    %25 = reshape %21 : tile<f64> -> tile<1xf64>
    %26 = broadcast %25 : tile<1xf64> -> tile<64xf64>
    %27 = mulf %13, %26 rounding<nearest_even> : tile<64xf64>
    %28 = subf %20, %27 rounding<nearest_even> : tile<64xf64>
    %29 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %30 = broadcast %29 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %31 = offset %30, %9 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %32 = store_ptr_tko weak %31, %28 token=%19 : tile<64xptr<f64>>, tile<64xf64> -> token
    return
  }
}
