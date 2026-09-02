cuda_tile.module @m {
  entry @leaky_relu(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
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
    %13 = constant <f64: 0.01> : tile<128xf64>
    %14 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %15 = broadcast %14 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %16 = offset %15, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %17, %18 = load_ptr_tko weak %16, %11, %12 token=%0 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %19 = mulf %17, %13 rounding<nearest_even> : tile<128xf64>
    %20 = cmpf less_than ordered %17, %12 : tile<128xf64> -> tile<128xi1>
    %21 = select %20, %19, %17 : tile<128xi1>, tile<128xf64>
    %22 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %23 = broadcast %22 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %24 = offset %23, %9 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %25 = store_ptr_tko weak %24, %21, %11 token=%18 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    return
  }
}
