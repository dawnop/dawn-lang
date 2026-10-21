cuda_tile.module @m {
  entry @sum(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 4> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %7 = make_tensor_view %6, shape = [1024], strides = [1] : tensor_view<1024xf64, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(128), padding_value = zero, tensor_view<1024xf64, strides=[1]>, dim_map=[0]>
    %9, %10 = load_view_tko weak %8[%5] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<1024xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %11 = constant <i32: 1> : tile<i32>
    %12 = addi %5, %11 : tile<i32>
    %13 = addi %5, %4 : tile<i32>
    %14 = for %15 in (%12 to %13, step %11) : tile<i32> iter_values(%16 = %9) -> (tile<128xf64>) {
      %17, %18 = load_view_tko weak %8[%15] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<1024xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
      %19 = addf %16, %17 rounding<nearest_even> : tile<128xf64>
      continue %19 : tile<128xf64>
    }
    %20, %21, %22 = get_num_tile_blocks : tile<i32>
    %23 = constant <i32: 128> : tile<i32>
    %24 = muli %20, %23 : tile<i32>
    %25 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %26 = make_tensor_view %25, shape = [%24], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %27 = make_partition_view %26 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %28, %29, %30 = get_tile_block_id : tile<i32>
    %31 = store_view_tko weak %14, %27[%28] token=%0 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
