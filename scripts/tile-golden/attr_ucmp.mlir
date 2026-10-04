cuda_tile.module @m {
  entry @attr_ucmp(%arg0: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 2147483632> : tile<i32>
    %2 = constant <i32: -2147483632> : tile<i32>
    %3 = constant <i32: 1> : tile<i32>
    %4 = constant <i32: 0> : tile<i32>
    %5, %6 = for %7 in (%1 to %2, step %3) : tile<i32> iter_values(%8 = %4, %9 = %0) -> (tile<i32>, token) {
      %10 = constant <i32: 1> : tile<i32>
      %11 = addi %8, %10 : tile<i32>
      continue %11, %9 : tile<i32>, token
    }
    %12 = constant <i32: 2147483632> : tile<i32>
    %13 = constant <i32: -2147483632> : tile<i32>
    %14 = constant <i32: 1> : tile<i32>
    %15, %16 = for %17 in (%12 to %13, step %14) unsigned : tile<i32> iter_values(%18 = %4, %19 = %6) -> (tile<i32>, token) {
      %20 = constant <i32: 1> : tile<i32>
      %21 = addi %18, %20 : tile<i32>
      continue %21, %19 : tile<i32>, token
    }
    %22 = reshape %5 : tile<i32> -> tile<1xi32>
    %23 = broadcast %22 : tile<1xi32> -> tile<128xi32>
    %24, %25, %26 = get_num_tile_blocks : tile<i32>
    %27 = constant <i32: 256> : tile<i32>
    %28 = muli %24, %27 : tile<i32>
    %29 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %30 = make_tensor_view %29, shape = [%28], strides = [1] : tile<i32> -> tensor_view<?xi32, strides=[1]>
    %31 = make_partition_view %30 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>
    %32, %33, %34 = get_tile_block_id : tile<i32>
    %35 = constant <i32: 2> : tile<i32>
    %36 = muli %32, %35 : tile<i32>
    %37 = store_view_tko weak %23, %31[%36] token=%16 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %38 = reshape %15 : tile<i32> -> tile<1xi32>
    %39 = broadcast %38 : tile<1xi32> -> tile<128xi32>
    %40 = constant <i32: 2> : tile<i32>
    %41 = muli %32, %40 : tile<i32>
    %42 = constant <i32: 1> : tile<i32>
    %43 = addi %41, %42 : tile<i32>
    %44 = store_view_tko weak %39, %31[%43] token=%37 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
