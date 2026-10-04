cuda_tile.module @m {
  entry @foldif(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 4> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 1> : tile<i32>
    %7 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %8 = make_tensor_view %7, shape = [1024], strides = [1] : tensor_view<1024xf64, strides=[1]>
    %9 = make_partition_view %8 : partition_view<tile=(128), padding_value = zero, tensor_view<1024xf64, strides=[1]>, dim_map=[0]>
    %10, %11 = load_view_tko weak %9[%5] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<1024xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %12 = addi %5, %6 : tile<i32>
    %13 = addi %5, %4 : tile<i32>
    %14, %15, %16, %17 = for %18 in (%12 to %13, step %6) : tile<i32> iter_values(%19 = %10, %20 = %10, %21 = %10, %22 = %11) -> (tile<128xf64>, tile<128xf64>, tile<128xf64>, token) {
      %23, %24 = load_view_tko weak %9[%18] token=%22 : partition_view<tile=(128), padding_value = zero, tensor_view<1024xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
      %25 = addf %19, %23 rounding<nearest_even> : tile<128xf64>
      %26 = maxf %20, %23 : tile<128xf64>
      %27 = minf %21, %23 : tile<128xf64>
      continue %25, %26, %27, %24 : tile<128xf64>, tile<128xf64>, tile<128xf64>, token
    }
    %28 = constant <i32: 0> : tile<i32>
    %29 = cmpi equal %1, %28, signed : tile<i32> -> tile<i1>
    %30 = if %29 -> (tile<128xf64>) {
      yield %14 : tile<128xf64>
    } else {
      %31 = subf %15, %16 rounding<nearest_even> : tile<128xf64>
      yield %31 : tile<128xf64>
    }
    %32, %33, %34 = get_num_tile_blocks : tile<i32>
    %35 = constant <i32: 128> : tile<i32>
    %36 = muli %32, %35 : tile<i32>
    %37 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %38 = make_tensor_view %37, shape = [%36], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %39 = make_partition_view %38 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %40, %41, %42 = get_tile_block_id : tile<i32>
    %43 = store_view_tko weak %30, %39[%40] token=%17 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
