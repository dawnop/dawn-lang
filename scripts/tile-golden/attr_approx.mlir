cuda_tile.module @m {
  entry @attr_approx(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 256> : tile<i32>
    %7 = muli %1, %6 : tile<i32>
    %8 = reshape %5 : tile<i32> -> tile<1xi32>
    %9 = broadcast %8 : tile<1xi32> -> tile<128xi32>
    %10 = iota : tile<128xi32>
    %11 = addi %9, %10 : tile<128xi32>
    %12 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %13 = broadcast %12 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %14 = offset %13, %11 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %15, %16 = load_ptr_tko weak %14 token=%0 : tile<128xptr<f64>> -> tile<128xf64>, token
    %17 = ftof %15 rounding<nearest_even> : tile<128xf64> -> tile<128xf32>
    %18 = sqrt %17 rounding<nearest_even> : tile<128xf32>
    %19 = ftof %18 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %20 = reshape %7 : tile<i32> -> tile<1xi32>
    %21 = broadcast %20 : tile<1xi32> -> tile<128xi32>
    %22 = iota : tile<128xi32>
    %23 = addi %21, %22 : tile<128xi32>
    %24 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %25 = broadcast %24 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %26 = offset %25, %23 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %27 = store_ptr_tko weak %26, %19 token=%16 : tile<128xptr<f64>>, tile<128xf64> -> token
    %28 = constant <i32: 128> : tile<i32>
    %29 = addi %7, %28 : tile<i32>
    %30 = sqrt %17 rounding<approx> : tile<128xf32>
    %31 = ftof %30 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %32 = reshape %29 : tile<i32> -> tile<1xi32>
    %33 = broadcast %32 : tile<1xi32> -> tile<128xi32>
    %34 = iota : tile<128xi32>
    %35 = addi %33, %34 : tile<128xi32>
    %36 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %37 = broadcast %36 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %38 = offset %37, %35 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %39 = store_ptr_tko weak %38, %31 token=%27 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
