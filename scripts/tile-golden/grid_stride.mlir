cuda_tile.module @m {
  entry @grid_stride(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_num_tile_blocks : tile<i32>
    %7 = constant <f64: 0.0> : tile<128xf64>
    %8 = constant <i32: 0> : tile<i32>
    %9 = constant <i32: 4> : tile<i32>
    %10 = constant <i32: 1> : tile<i32>
    %11, %12 = for %13 in (%8 to %9, step %10) : tile<i32> iter_values(%14 = %7, %15 = %0) -> (tile<128xf64>, token) {
      %16 = muli %13, %4 : tile<i32>
      %17 = addi %1, %16 : tile<i32>
      %18 = constant <i32: 128> : tile<i32>
      %19 = muli %17, %18 : tile<i32>
      %20 = reshape %19 : tile<i32> -> tile<1xi32>
      %21 = broadcast %20 : tile<1xi32> -> tile<128xi32>
      %22 = iota : tile<128xi32>
      %23 = addi %21, %22 : tile<128xi32>
      %24 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
      %25 = broadcast %24 : tile<1xptr<f64>> -> tile<128xptr<f64>>
      %26 = offset %25, %23 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
      %27, %28 = load_ptr_tko weak %26 token=%15 : tile<128xptr<f64>> -> tile<128xf64>, token
      %29 = constant <f64: 2.0> : tile<128xf64>
      %30 = mulf %27, %29 rounding<nearest_even> : tile<128xf64>
      %31 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
      %32 = broadcast %31 : tile<1xptr<f64>> -> tile<128xptr<f64>>
      %33 = offset %32, %23 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
      %34 = store_ptr_tko weak %33, %30 token=%28 : tile<128xptr<f64>>, tile<128xf64> -> token
      continue %14, %34 : tile<128xf64>, token
    }
    return
  }
}
