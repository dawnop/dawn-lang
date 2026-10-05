cuda_tile.module @m {
  entry @grid_stride(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_num_tile_blocks : tile<i32>
    %7 = constant <i32: 0> : tile<i32>
    %8 = constant <i32: 4> : tile<i32>
    %9 = constant <i32: 1> : tile<i32>
    %10 = for %11 in (%7 to %8, step %9) : tile<i32> iter_values(%12 = %0) -> (token) {
      %13 = muli %11, %4 : tile<i32>
      %14 = addi %1, %13 : tile<i32>
      %15 = constant <i32: 128> : tile<i32>
      %16 = muli %14, %15 : tile<i32>
      %17 = reshape %16 : tile<i32> -> tile<1xi32>
      %18 = broadcast %17 : tile<1xi32> -> tile<128xi32>
      %19 = iota : tile<128xi32>
      %20 = addi %18, %19 : tile<128xi32>
      %21 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
      %22 = broadcast %21 : tile<1xptr<f64>> -> tile<128xptr<f64>>
      %23 = offset %22, %20 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
      %24, %25 = load_ptr_tko weak %23 token=%12 : tile<128xptr<f64>> -> tile<128xf64>, token
      %26 = constant <f64: 2.0> : tile<128xf64>
      %27 = mulf %24, %26 rounding<nearest_even> : tile<128xf64>
      %28 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
      %29 = broadcast %28 : tile<1xptr<f64>> -> tile<128xptr<f64>>
      %30 = offset %29, %20 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
      %31 = store_ptr_tko weak %30, %27 token=%25 : tile<128xptr<f64>>, tile<128xf64> -> token
      continue %31 : token
    }
    return
  }
}
