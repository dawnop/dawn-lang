cuda_tile.module @m {
  entry @elemops(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
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
    %13 = constant <f64: 2.0> : tile<128xf64>
    %14 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %15 = broadcast %14 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %16 = offset %15, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %17, %18 = load_ptr_tko weak %16, %11, %12 token=%0 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %19 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %20 = broadcast %19 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %21 = offset %20, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %22, %23 = load_ptr_tko weak %21, %11, %12 token=%18 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %24 = subf %17, %22 rounding<nearest_even> : tile<128xf64>
    %25 = mulf %17, %22 rounding<nearest_even> : tile<128xf64>
    %26 = divf %25, %13 rounding<nearest_even> : tile<128xf64>
    %27 = negf %26 : tile<128xf64>
    %28 = absf %27 : tile<128xf64>
    %29 = fma %17, %13, %22 rounding<nearest_even> : tile<128xf64>
    %30 = cmpf less_than ordered %17, %22 : tile<128xf64> -> tile<128xi1>
    %31 = select %30, %24, %28 : tile<128xi1>, tile<128xf64>
    %32 = cmpf greater_than_or_equal ordered %17, %22 : tile<128xf64> -> tile<128xi1>
    %33 = select %32, %31, %29 : tile<128xi1>, tile<128xf64>
    %34 = cmpf equal ordered %17, %22 : tile<128xf64> -> tile<128xi1>
    %35 = minf %17, %22 : tile<128xf64>
    %36 = select %34, %35, %33 : tile<128xi1>, tile<128xf64>
    %37 = cmpf not_equal ordered %17, %22 : tile<128xf64> -> tile<128xi1>
    %38 = maxf %17, %22 : tile<128xf64>
    %39 = select %37, %36, %38 : tile<128xi1>, tile<128xf64>
    %40 = cmpf greater_than ordered %17, %22 : tile<128xf64> -> tile<128xi1>
    %41 = select %40, %39, %24 : tile<128xi1>, tile<128xf64>
    %42 = cmpf less_than_or_equal ordered %17, %22 : tile<128xf64> -> tile<128xi1>
    %43 = select %42, %41, %28 : tile<128xi1>, tile<128xf64>
    %44 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %45 = broadcast %44 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %46 = offset %45, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %47 = store_ptr_tko weak %46, %43, %11 token=%23 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    return
  }
}
