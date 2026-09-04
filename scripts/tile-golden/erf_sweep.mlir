cuda_tile.module @m {
  entry @erf_sweep(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
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
    %18 = absf %16 : tile<128xf64>
    %19 = constant <f64: 1.0> : tile<128xf64>
    %20 = constant <f64: 0.3275911> : tile<128xf64>
    %21 = fma %20, %18, %19 rounding<nearest_even> : tile<128xf64>
    %22 = divf %19, %21 rounding<nearest_even> : tile<128xf64>
    %23 = constant <f64: 1.061405429> : tile<128xf64>
    %24 = constant <f64: -1.453152027> : tile<128xf64>
    %25 = fma %22, %23, %24 rounding<nearest_even> : tile<128xf64>
    %26 = constant <f64: 1.421413741> : tile<128xf64>
    %27 = fma %22, %25, %26 rounding<nearest_even> : tile<128xf64>
    %28 = constant <f64: -0.284496736> : tile<128xf64>
    %29 = fma %22, %27, %28 rounding<nearest_even> : tile<128xf64>
    %30 = constant <f64: 0.254829592> : tile<128xf64>
    %31 = fma %22, %29, %30 rounding<nearest_even> : tile<128xf64>
    %32 = mulf %22, %31 rounding<nearest_even> : tile<128xf64>
    %33 = mulf %18, %18 rounding<nearest_even> : tile<128xf64>
    %34 = negf %33 : tile<128xf64>
    %35 = exp %34 : tile<128xf64>
    %36 = mulf %32, %35 rounding<nearest_even> : tile<128xf64>
    %37 = subf %19, %36 rounding<nearest_even> : tile<128xf64>
    %38 = constant <f64: 0.0> : tile<128xf64>
    %39 = cmpf less_than ordered %16, %38 : tile<128xf64> -> tile<128xi1>
    %40 = negf %37 : tile<128xf64>
    %41 = select %39, %40, %37 : tile<128xi1>, tile<128xf64>
    %42 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %43 = broadcast %42 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %44 = offset %43, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %45 = store_ptr_tko weak %44, %41, %11 token=%17 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    return
  }
}
