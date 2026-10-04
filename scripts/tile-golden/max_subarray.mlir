cuda_tile.module @m {
  entry @max_subarray(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = reshape %1 : tile<i32> -> tile<1xi32>
    %3 = broadcast %2 : tile<1xi32> -> tile<128xi32>
    %4 = iota : tile<128xi32>
    %5 = addi %3, %4 : tile<128xi32>
    %6 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %7 = make_tensor_view %6, shape = [100], strides = [1] : tensor_view<100xi32, strides=[1]>
    %8 = make_partition_view %7 : partition_view<tile=(128), padding_value = zero, tensor_view<100xi32, strides=[1]>, dim_map=[0]>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13 = load_view_tko weak %8[%9] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<100xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %14 = scan %12 dim=0 reverse=false identities=[0 : i32] : tile<128xi32> -> tile<128xi32> (%15: tile<i32>, %16: tile<i32>) {
      %17 = addi %15, %16 : tile<i32>
      yield %17 : tile<i32>
    }
    %18 = constant <i32: 7> : tile<128xi32>
    %19 = cmpi greater_than_or_equal %5, %18, signed : tile<128xi32> -> tile<128xi1>
    %20 = constant <i32: 107> : tile<128xi32>
    %21 = cmpi less_than %5, %20, signed : tile<128xi32> -> tile<128xi1>
    %22 = constant <i1: 0> : tile<128xi1>
    %23 = select %19, %21, %22 : tile<128xi1>, tile<128xi1>
    %24 = constant <i32: 7> : tile<128xi32>
    %25 = subi %5, %24 : tile<128xi32>
    %26 = constant <i32: 0> : tile<128xi32>
    %27 = maxi %25, %26 signed : tile<128xi32>
    %28 = reshape %arg0 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %29 = broadcast %28 : tile<1xptr<i32>> -> tile<128xptr<i32>>
    %30 = offset %29, %27 : tile<128xptr<i32>>, tile<128xi32> -> tile<128xptr<i32>>
    %31, %32 = load_ptr_tko weak %30, %23, %26 token=%13 : tile<128xptr<i32>>, tile<128xi1>, tile<128xi32> -> tile<128xi32>, token
    %33 = scan %31 dim=0 reverse=false identities=[0 : i32] : tile<128xi32> -> tile<128xi32> (%34: tile<i32>, %35: tile<i32>) {
      %36 = addi %34, %35 : tile<i32>
      yield %36 : tile<i32>
    }
    %37 = constant <i32: 6> : tile<128xi32>
    %38 = cmpi greater_than_or_equal %5, %37, signed : tile<128xi32> -> tile<128xi1>
    %39 = constant <i32: 100> : tile<128xi32>
    %40 = cmpi less_than %5, %39, signed : tile<128xi32> -> tile<128xi1>
    %41 = constant <i1: 0> : tile<128xi1>
    %42 = select %38, %40, %41 : tile<128xi1>, tile<128xi1>
    %43 = subi %14, %33 : tile<128xi32>
    %44 = constant <i32: -2000000000> : tile<128xi32>
    %45 = select %42, %43, %44 : tile<128xi1>, tile<128xi32>
    %46 = reduce %45 dim=0 identities=[-2000000000 : i32] : tile<128xi32> -> tile<i32> (%47: tile<i32>, %48: tile<i32>) {
      %49 = maxi %47, %48 signed : tile<i32>
      yield %49 : tile<i32>
    }
    %50 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %51 = make_tensor_view %50, shape = [1], strides = [1] : tensor_view<1xi32, strides=[1]>
    %52 = make_partition_view %51 : partition_view<tile=(1), padding_value = zero, tensor_view<1xi32, strides=[1]>, dim_map=[0]>
    %53 = reshape %46 : tile<i32> -> tile<1xi32>
    %54 = broadcast %53 : tile<1xi32> -> tile<1xi32>
    %55 = store_view_tko weak %54, %52[%9] token=%32 : tile<1xi32>, partition_view<tile=(1), padding_value = zero, tensor_view<1xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
