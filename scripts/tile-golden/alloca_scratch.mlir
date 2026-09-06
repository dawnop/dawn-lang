cuda_tile.module @m {
  entry @alloca_scratch(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 0> : tile<i32>
    %7 = reshape %6 : tile<i32> -> tile<1xi32>
    %8 = broadcast %7 : tile<1xi32> -> tile<128xi32>
    %9 = iota : tile<128xi32>
    %10 = addi %8, %9 : tile<128xi32>
    %11 = alloca num_elem = 192, alignment = 8 : tile<ptr<f64>>
    %12 = reshape %11 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %13 = broadcast %12 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %14 = offset %13, %10 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %15 = reshape %5 : tile<i32> -> tile<1xi32>
    %16 = broadcast %15 : tile<1xi32> -> tile<128xi32>
    %17 = iota : tile<128xi32>
    %18 = addi %16, %17 : tile<128xi32>
    %19 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %20 = broadcast %19 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %21 = offset %20, %18 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %22, %23 = load_ptr_tko weak %21 token=%0 : tile<128xptr<f64>> -> tile<128xf64>, token
    %24 = addf %22, %22 rounding<nearest_even> : tile<128xf64>
    %25 = store_ptr_tko weak %14, %24 token=%23 : tile<128xptr<f64>>, tile<128xf64> -> token
    %26, %27 = load_ptr_tko weak %14 token=%25 : tile<128xptr<f64>> -> tile<128xf64>, token
    %28 = addf %26, %22 rounding<nearest_even> : tile<128xf64>
    %29 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %30 = broadcast %29 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %31 = offset %30, %18 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %32 = store_ptr_tko weak %31, %28 token=%27 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
