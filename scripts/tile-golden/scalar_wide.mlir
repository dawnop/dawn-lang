cuda_tile.module @m {
  entry @scalar_wide(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<i64>>, %arg2: tile<f64>, %arg3: tile<i64>, %arg4: tile<ptr<f64>>, %arg5: tile<ptr<i64>>) {
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
    %15 = reshape %arg2 : tile<f64> -> tile<1xf64>
    %16 = broadcast %15 : tile<1xf64> -> tile<64xf64>
    %17 = mulf %13, %16 rounding<nearest_even> : tile<64xf64>
    %18 = reshape %arg4 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %19 = broadcast %18 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %20 = offset %19, %9 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %21 = store_ptr_tko weak %20, %17 token=%14 : tile<64xptr<f64>>, tile<64xf64> -> token
    %22 = reshape %arg1 : tile<ptr<i64>> -> tile<1xptr<i64>>
    %23 = broadcast %22 : tile<1xptr<i64>> -> tile<64xptr<i64>>
    %24 = offset %23, %9 : tile<64xptr<i64>>, tile<64xi32> -> tile<64xptr<i64>>
    %25, %26 = load_ptr_tko weak %24 token=%21 : tile<64xptr<i64>> -> tile<64xi64>, token
    %27 = reshape %arg3 : tile<i64> -> tile<1xi64>
    %28 = broadcast %27 : tile<1xi64> -> tile<64xi64>
    %29 = addi %25, %28 : tile<64xi64>
    %30 = reshape %arg5 : tile<ptr<i64>> -> tile<1xptr<i64>>
    %31 = broadcast %30 : tile<1xptr<i64>> -> tile<64xptr<i64>>
    %32 = offset %31, %9 : tile<64xptr<i64>>, tile<64xi32> -> tile<64xptr<i64>>
    %33 = store_ptr_tko weak %32, %29 token=%26 : tile<64xptr<i64>>, tile<64xi64> -> token
    return
  }
}
