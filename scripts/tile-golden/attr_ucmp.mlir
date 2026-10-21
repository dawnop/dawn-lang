cuda_tile.module @m {
  entry @attr_ucmp(%arg0: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 2147483632> : tile<i32>
    %2 = constant <i32: -2147483632> : tile<i32>
    %3 = constant <i32: 1> : tile<i32>
    %4 = constant <i32: 0> : tile<i32>
    %5 = for %6 in (%1 to %2, step %3) : tile<i32> iter_values(%7 = %4) -> (tile<i32>) {
      %8 = constant <i32: 1> : tile<i32>
      %9 = addi %7, %8 : tile<i32>
      continue %9 : tile<i32>
    }
    %10 = constant <i32: 2147483632> : tile<i32>
    %11 = constant <i32: -2147483632> : tile<i32>
    %12 = constant <i32: 1> : tile<i32>
    %13 = for %14 in (%10 to %11, step %12) unsigned : tile<i32> iter_values(%15 = %4) -> (tile<i32>) {
      %16 = constant <i32: 1> : tile<i32>
      %17 = addi %15, %16 : tile<i32>
      continue %17 : tile<i32>
    }
    %18 = reshape %5 : tile<i32> -> tile<1xi32>
    %19 = broadcast %18 : tile<1xi32> -> tile<128xi32>
    %20, %21, %22 = get_num_tile_blocks : tile<i32>
    %23 = constant <i32: 256> : tile<i32>
    %24 = muli %20, %23 : tile<i32>
    %25 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %26 = make_tensor_view %25, shape = [%24], strides = [1] : tile<i32> -> tensor_view<?xi32, strides=[1]>
    %27 = make_partition_view %26 : partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>
    %28, %29, %30 = get_tile_block_id : tile<i32>
    %31 = constant <i32: 2> : tile<i32>
    %32 = muli %28, %31 : tile<i32>
    %33 = store_view_tko weak %19, %27[%32] token=%0 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %34 = reshape %13 : tile<i32> -> tile<1xi32>
    %35 = broadcast %34 : tile<1xi32> -> tile<128xi32>
    %36 = constant <i32: 2> : tile<i32>
    %37 = muli %28, %36 : tile<i32>
    %38 = constant <i32: 1> : tile<i32>
    %39 = addi %37, %38 : tile<i32>
    %40 = store_view_tko weak %35, %27[%39] token=%33 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<?xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
