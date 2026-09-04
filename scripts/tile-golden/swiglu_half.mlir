cuda_tile.module @m {
  entry @swiglu_half(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = constant <i32: 500> : tile<128xi32>
    %11 = cmpi less_than %9, %10, signed : tile<128xi32> -> tile<128xi1>
    %12 = constant <f64: 0.0> : tile<128xf64>
    %13 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %14 = broadcast %13 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %15 = offset %14, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %16, %17 = load_ptr_tko weak %15, %11, %12 token=%0 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %18 = constant <i32: 500> : tile<i32>
    %19 = addi %5, %18 : tile<i32>
    %20 = reshape %19 : tile<i32> -> tile<1xi32>
    %21 = broadcast %20 : tile<1xi32> -> tile<128xi32>
    %22 = iota : tile<128xi32>
    %23 = addi %21, %22 : tile<128xi32>
    %24 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %25 = broadcast %24 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %26 = offset %25, %23 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %27, %28 = load_ptr_tko weak %26, %11, %12 token=%17 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %29 = constant <f64: 1.0> : tile<128xf64>
    %30 = negf %16 : tile<128xf64>
    %31 = exp %30 : tile<128xf64>
    %32 = addf %29, %31 rounding<nearest_even> : tile<128xf64>
    %33 = divf %16, %32 rounding<nearest_even> : tile<128xf64>
    %34 = mulf %33, %27 rounding<nearest_even> : tile<128xf64>
    %35 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %36 = broadcast %35 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %37 = offset %36, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %38 = store_ptr_tko weak %37, %34, %11 token=%28 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    return
  }
}
