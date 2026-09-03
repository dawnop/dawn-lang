cuda_tile.module @m {
  entry @reverse(%arg0: tile<ptr<f64>>) {
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
    %18 = constant <i32: 999> : tile<i32>
    %19 = constant <i32: -1> : tile<i32>
    %20 = muli %5, %19 : tile<i32>
    %21 = addi %18, %20 : tile<i32>
    %22 = reshape %21 : tile<i32> -> tile<1xi32>
    %23 = broadcast %22 : tile<1xi32> -> tile<128xi32>
    %24 = iota : tile<128xi32>
    %25 = constant <i32: -1> : tile<128xi32>
    %26 = muli %24, %25 : tile<128xi32>
    %27 = addi %23, %26 : tile<128xi32>
    %28 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %29 = broadcast %28 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %30 = offset %29, %27 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %31, %32 = load_ptr_tko weak %30, %11, %12 token=%17 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %33 = store_ptr_tko weak %30, %16, %11 token=%32 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    %34 = store_ptr_tko weak %15, %31, %11 token=%33 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    return
  }
}
