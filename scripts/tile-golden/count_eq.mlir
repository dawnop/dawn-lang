cuda_tile.module @m {
  entry @count_eq(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %2 = make_tensor_view %1, shape = [1000], strides = [1] : tensor_view<1000xi32, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xi32, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1024xi32>, token
    %9 = constant <i32: 7> : tile<1024xi32>
    %10 = cmpi equal %7, %9, signed : tile<1024xi32> -> tile<1024xi1>
    %11 = exti %10 unsigned : tile<1024xi1> -> tile<1024xi32>
    %12 = reduce %11 dim=0 identities=[0 : i32] : tile<1024xi32> -> tile<i32> (%13: tile<i32>, %14: tile<i32>) {
      %15 = addi %13, %14 : tile<i32>
      yield %15 : tile<i32>
    }
    %16 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %17 = make_tensor_view %16, shape = [1], strides = [1] : tensor_view<1xi32, strides=[1]>
    %18 = make_partition_view %17 : partition_view<tile=(1), padding_value = zero, tensor_view<1xi32, strides=[1]>, dim_map=[0]>
    %19 = reshape %12 : tile<i32> -> tile<1xi32>
    %20 = broadcast %19 : tile<1xi32> -> tile<1xi32>
    %21 = store_view_tko weak %20, %18[%4] token=%8 : tile<1xi32>, partition_view<tile=(1), padding_value = zero, tensor_view<1xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
