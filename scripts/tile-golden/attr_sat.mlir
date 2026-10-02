cuda_tile.module @m {
  entry @attr_sat(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<i32>>) {
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
    %17 = constant <f64: -2.147483649E9> : tile<128xf64>
    %18 = cmpf greater_than ordered %15, %17 : tile<128xf64> -> tile<128xi1>
    %19 = constant <f64: 2.147483648E9> : tile<128xf64>
    %20 = cmpf less_than ordered %15, %19 : tile<128xf64> -> tile<128xi1>
    %21 = constant <i1: 0> : tile<128xi1>
    %22 = select %18, %20, %21 : tile<128xi1>, tile<128xi1>
    %23 = ftoi %15 signed rounding<nearest_int_to_zero> saturating : tile<128xf64> -> tile<128xi32>
    %24 = reshape %7 : tile<i32> -> tile<1xi32>
    %25 = broadcast %24 : tile<1xi32> -> tile<128xi32>
    %26 = iota : tile<128xi32>
    %27 = addi %25, %26 : tile<128xi32>
    %28 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %29 = broadcast %28 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %30 = offset %29, %27 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %31 = store_ptr_tko weak %30, %23 token=%16 : tile<128xptr<i32>>, tile<128xi32> -> token
    %32 = constant <i32: 128> : tile<i32>
    %33 = addi %7, %32 : tile<i32>
    %34 = ftoi %15 signed rounding<nearest_int_to_zero> : tile<128xf64> -> tile<128xi32>
    %35 = reshape %33 : tile<i32> -> tile<1xi32>
    %36 = broadcast %35 : tile<1xi32> -> tile<128xi32>
    %37 = iota : tile<128xi32>
    %38 = addi %36, %37 : tile<128xi32>
    %39 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %40 = broadcast %39 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %41 = offset %40, %38 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %42 = store_ptr_tko weak %41, %34, %22 token=%31 : tile<128xptr<i32>>, tile<128xi32>, tile<128xi1> -> token
    return
  }
}
