cuda_tile.module @m {
  entry @sum_diff(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = constant <i32: 1000> : tile<128xi32>
    %11 = cmpi less_than %9, %10, signed : tile<128xi32> -> tile<128xi1>
    %12 = constant <f64: 0.0> : tile<128xf64>
    %13 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %14 = broadcast %13 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %15 = offset %14, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %16, %17 = load_ptr_tko weak %15, %11, %12 token=%0 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %18 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %19 = broadcast %18 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %20 = offset %19, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %21, %22 = load_ptr_tko weak %20, %11, %12 token=%17 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %23 = addf %16, %21 rounding<nearest_even> : tile<128xf64>
    %24 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %25 = broadcast %24 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %26 = offset %25, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %27 = store_ptr_tko weak %26, %23, %11 token=%22 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    %28 = subf %16, %21 rounding<nearest_even> : tile<128xf64>
    %29 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %30 = broadcast %29 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %31 = offset %30, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %32 = store_ptr_tko weak %31, %28, %11 token=%27 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    return
  }
}
