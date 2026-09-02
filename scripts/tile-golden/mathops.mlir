cuda_tile.module @m {
  entry @mathops(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
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
    %12 = constant <f64: 1.0> : tile<128xf64>
    %13 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %14 = broadcast %13 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %15 = offset %14, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %16, %17 = load_ptr_tko weak %15, %11, %12 token=%0 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %18 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %19 = broadcast %18 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %20 = offset %19, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %21, %22 = load_ptr_tko weak %20, %11, %12 token=%17 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %23 = exp %16 : tile<128xf64>
    %24 = exp2 %16 : tile<128xf64>
    %25 = addf %23, %24 rounding<nearest_even> : tile<128xf64>
    %26 = log %16 : tile<128xf64>
    %27 = addf %25, %26 rounding<nearest_even> : tile<128xf64>
    %28 = log2 %16 : tile<128xf64>
    %29 = addf %27, %28 rounding<nearest_even> : tile<128xf64>
    %30 = sqrt %16 rounding<nearest_even> : tile<128xf64>
    %31 = addf %29, %30 rounding<nearest_even> : tile<128xf64>
    %32 = rsqrt %16 : tile<128xf64>
    %33 = addf %31, %32 rounding<nearest_even> : tile<128xf64>
    %34 = tanh %16 : tile<128xf64>
    %35 = addf %33, %34 rounding<nearest_even> : tile<128xf64>
    %36 = pow %16, %21 : tile<128xf64>
    %37 = addf %35, %36 rounding<nearest_even> : tile<128xf64>
    %38 = floor %21 : tile<128xf64>
    %39 = addf %37, %38 rounding<nearest_even> : tile<128xf64>
    %40 = ceil %21 : tile<128xf64>
    %41 = addf %39, %40 rounding<nearest_even> : tile<128xf64>
    %42 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %43 = broadcast %42 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %44 = offset %43, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %45 = store_ptr_tko weak %44, %41, %11 token=%22 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    return
  }
}
