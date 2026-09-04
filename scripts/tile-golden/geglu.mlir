cuda_tile.module @m {
  entry @geglu(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = constant <i32: 300> : tile<128xi32>
    %11 = cmpi less_than %9, %10, signed : tile<128xi32> -> tile<128xi1>
    %12 = constant <f64: 0.0> : tile<128xf64>
    %13 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %14 = broadcast %13 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %15 = offset %14, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %16, %17 = load_ptr_tko weak %15, %11, %12 token=%0 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %18 = constant <i32: 300> : tile<i32>
    %19 = addi %5, %18 : tile<i32>
    %20 = reshape %19 : tile<i32> -> tile<1xi32>
    %21 = broadcast %20 : tile<1xi32> -> tile<128xi32>
    %22 = iota : tile<128xi32>
    %23 = addi %21, %22 : tile<128xi32>
    %24 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %25 = broadcast %24 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %26 = offset %25, %23 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %27, %28 = load_ptr_tko weak %26, %11, %12 token=%17 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %29 = constant <f64: 0.7071067811865475> : tile<128xf64>
    %30 = mulf %27, %29 rounding<nearest_even> : tile<128xf64>
    %31 = absf %30 : tile<128xf64>
    %32 = constant <f64: 1.0> : tile<128xf64>
    %33 = constant <f64: 0.3275911> : tile<128xf64>
    %34 = fma %33, %31, %32 rounding<nearest_even> : tile<128xf64>
    %35 = divf %32, %34 rounding<nearest_even> : tile<128xf64>
    %36 = constant <f64: 1.061405429> : tile<128xf64>
    %37 = constant <f64: -1.453152027> : tile<128xf64>
    %38 = fma %35, %36, %37 rounding<nearest_even> : tile<128xf64>
    %39 = constant <f64: 1.421413741> : tile<128xf64>
    %40 = fma %35, %38, %39 rounding<nearest_even> : tile<128xf64>
    %41 = constant <f64: -0.284496736> : tile<128xf64>
    %42 = fma %35, %40, %41 rounding<nearest_even> : tile<128xf64>
    %43 = constant <f64: 0.254829592> : tile<128xf64>
    %44 = fma %35, %42, %43 rounding<nearest_even> : tile<128xf64>
    %45 = mulf %35, %44 rounding<nearest_even> : tile<128xf64>
    %46 = mulf %31, %31 rounding<nearest_even> : tile<128xf64>
    %47 = negf %46 : tile<128xf64>
    %48 = exp %47 : tile<128xf64>
    %49 = mulf %45, %48 rounding<nearest_even> : tile<128xf64>
    %50 = subf %32, %49 rounding<nearest_even> : tile<128xf64>
    %51 = constant <f64: 0.0> : tile<128xf64>
    %52 = cmpf less_than ordered %30, %51 : tile<128xf64> -> tile<128xi1>
    %53 = negf %50 : tile<128xf64>
    %54 = select %52, %53, %50 : tile<128xi1>, tile<128xf64>
    %55 = constant <f64: 0.5> : tile<128xf64>
    %56 = mulf %55, %27 rounding<nearest_even> : tile<128xf64>
    %57 = constant <f64: 1.0> : tile<128xf64>
    %58 = addf %57, %54 rounding<nearest_even> : tile<128xf64>
    %59 = mulf %56, %58 rounding<nearest_even> : tile<128xf64>
    %60 = mulf %16, %59 rounding<nearest_even> : tile<128xf64>
    %61 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %62 = broadcast %61 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %63 = offset %62, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %64 = store_ptr_tko weak %63, %60, %11 token=%28 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    return
  }
}
