cuda_tile.module @m {
  entry @print_tile(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %2 = make_tensor_view %1, shape = [128], strides = [1] : tensor_view<128xi32, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %9 = reduce %7 dim=0 identities=[0 : i32] : tile<128xi32> -> tile<i32> (%10: tile<i32>, %11: tile<i32>) {
      %12 = addi %10, %11 : tile<i32>
      yield %12 : tile<i32>
    }
    %13 = reduce %7 dim=0 identities=[0 : i32] : tile<128xi32> -> tile<i32> (%14: tile<i32>, %15: tile<i32>) {
      %16 = maxi %14, %15 signed : tile<i32>
      yield %16 : tile<i32>
    }
    %17 = print_tko "print_tile sum=%d max=%d\n", %9, %13 token=%8 : tile<i32>, tile<i32> -> token
    %18 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %19 = make_tensor_view %18, shape = [384], strides = [1] : tensor_view<384xi32, strides=[1]>
    %20 = make_partition_view %19 : partition_view<tile=(128), padding_value = zero, tensor_view<384xi32, strides=[1]>, dim_map=[0]>
    %21 = constant <i32: 4> : tile<i32>
    %22 = muli %4, %21 : tile<i32>
    %23 = store_view_tko weak %7, %20[%22] token=%17 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<384xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %24 = reshape %9 : tile<i32> -> tile<1xi32>
    %25 = broadcast %24 : tile<1xi32> -> tile<128xi32>
    %26 = constant <i32: 4> : tile<i32>
    %27 = muli %4, %26 : tile<i32>
    %28 = constant <i32: 1> : tile<i32>
    %29 = addi %27, %28 : tile<i32>
    %30 = store_view_tko weak %25, %20[%29] token=%23 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<384xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %31 = reshape %13 : tile<i32> -> tile<1xi32>
    %32 = broadcast %31 : tile<1xi32> -> tile<128xi32>
    %33 = constant <i32: 4> : tile<i32>
    %34 = muli %4, %33 : tile<i32>
    %35 = constant <i32: 2> : tile<i32>
    %36 = addi %34, %35 : tile<i32>
    %37 = store_view_tko weak %32, %20[%36] token=%30 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<384xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
